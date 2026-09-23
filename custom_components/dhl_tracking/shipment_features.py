"""Derive structured delivery features from a DHL tracking payload.

What the official API actually offers
-------------------------------------
``details.valueAddedServices.services[]`` is the only *structured* source, and
its ``serviceType`` enum is short (OpenAPI 1.5.6)::

    bulky | pickup | gogreen | priority | extraInsurance
    directInjection | cashOnDelivery | importFees

Everything a German parcel recipient actually cares about - Empfaengerunter-
schrift, Ident-Check, Alterssichtpruefung, Wunschtag/-ort/-nachbar - is *not*
in that enum. DHL ships it inside the free-text ``details.product.productName``
instead, e.g. ``"DHL PAKET, Empfaengerunterschrift"``.

So the structured fields are used first and the product text is only parsed for
what they cannot express. Every fragment that is not recognised is handed
through as ``services_raw`` so no information is silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .const import (
    SERVICE_AGE_CHECK,
    SERVICE_BULKY,
    SERVICE_CASH_ON_DELIVERY,
    SERVICE_DIRECT_INJECTION,
    SERVICE_EXTRA_INSURANCE,
    SERVICE_GOGREEN,
    SERVICE_IDENT_CHECK,
    SERVICE_IMPORT_FEES,
    SERVICE_NO_NEIGHBOUR_DELIVERY,
    SERVICE_PICKUP,
    SERVICE_PREFERRED_DAY,
    SERVICE_PREFERRED_LOCATION,
    SERVICE_PREFERRED_NEIGHBOUR,
    SERVICE_PRIORITY,
    SERVICE_RETURN,
    SERVICE_SIGNATURE,
)

# `ValueAddedService.serviceType` -> our normalised key.
VAS_TYPE_MAP: dict[str, str] = {
    "bulky": SERVICE_BULKY,
    "cashOnDelivery": SERVICE_CASH_ON_DELIVERY,
    "directInjection": SERVICE_DIRECT_INJECTION,
    "extraInsurance": SERVICE_EXTRA_INSURANCE,
    "gogreen": SERVICE_GOGREEN,
    "importFees": SERVICE_IMPORT_FEES,
    "pickup": SERVICE_PICKUP,
    "priority": SERVICE_PRIORITY,
}

# Ordered on purpose: the first match wins per text fragment, and the negative
# "no neighbour" wording has to be tested before the positive "Wunschnachbar".
TEXT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        SERVICE_NO_NEIGHBOUR_DELIVERY,
        (
            "keine nachbarschaftsabgabe",
            "ohne nachbarschaftsabgabe",
            "keine nachbarschaftszustellung",
            "nicht beim nachbarn",
            "no neighbour delivery",
            "no neighbor delivery",
            "eigenhandig",
        ),
    ),
    (
        SERVICE_IDENT_CHECK,
        ("ident-check", "identcheck", "ident check", "postident", "identity check"),
    ),
    (
        SERVICE_AGE_CHECK,
        (
            "alterssichtprufung",
            "alterssicht",
            "altersnachweis",
            "altersprufung",
            "age check",
            "age verification",
        ),
    ),
    (
        SERVICE_SIGNATURE,
        (
            "empfangerunterschrift",
            "unterschrift",
            "signature",
            "signed for",
        ),
    ),
    (
        SERVICE_CASH_ON_DELIVERY,
        ("nachnahme", "cash on delivery", "cash-on-delivery"),
    ),
    (SERVICE_PREFERRED_DAY, ("wunschtag", "preferred day")),
    (
        SERVICE_PREFERRED_LOCATION,
        ("wunschort", "ablageort", "abstellgenehmigung", "preferred location"),
    ),
    (SERVICE_PREFERRED_NEIGHBOUR, ("wunschnachbar", "preferred neighbour")),
    (SERVICE_BULKY, ("sperrgut", "bulky goods")),
    (SERVICE_RETURN, ("retoure", "rucksendung", "ruckversand", "return shipment")),
)

# A signature (or an equivalent handover confirmation) has to be given for
# these; the parcel is not left at the door.
SIGNATURE_SERVICES = frozenset(
    {
        SERVICE_SIGNATURE,
        SERVICE_IDENT_CHECK,
        SERVICE_AGE_CHECK,
        SERVICE_CASH_ON_DELIVERY,
    }
)

# The recipient has to show an ID document.
ID_SERVICES = frozenset({SERVICE_IDENT_CHECK, SERVICE_AGE_CHECK})

_FRAGMENT_SPLIT = re.compile(r"[,;/|+&]|\s+-\s+")
_NUMBER = r"(?P<amount>\d[\d.,]*\d|\d)"
_CURRENCY = r"(?P<currency>[A-Z]{3}|[€$£])"
_AMOUNT_AFTER = re.compile(rf"{_NUMBER}\s*{_CURRENCY}")
_AMOUNT_BEFORE = re.compile(rf"{_CURRENCY}\s*{_NUMBER}")
_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}

# Fold the umlauts and the sharp s so the patterns above stay ASCII and match
# regardless of how DHL spells them.
_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e"})


def _normalise(text: str) -> str:
    """Return a lower-cased, umlaut-folded version of a text fragment."""
    return text.strip().lower().translate(_FOLD)


@dataclass(frozen=True, slots=True)
class ShipmentFeatures:
    """Delivery features derived from one shipment payload."""

    services: tuple[str, ...] = ()
    services_raw: tuple[str, ...] = ()
    cash_on_delivery_amount: float | None = None
    cash_on_delivery_currency: str | None = None

    @property
    def signature_required(self) -> bool:
        """Return whether the parcel is handed over against a signature."""
        return bool(SIGNATURE_SERVICES.intersection(self.services))

    @property
    def id_required(self) -> bool:
        """Return whether the recipient has to show an ID document."""
        return bool(ID_SERVICES.intersection(self.services))

    def as_attributes(self) -> dict[str, Any]:
        """Return the entity attributes for these features."""
        attrs: dict[str, Any] = {
            "services": list(self.services),
            "signature_required": self.signature_required,
            "id_required": self.id_required,
        }
        if self.services_raw:
            attrs["services_raw"] = list(self.services_raw)
        if self.cash_on_delivery_amount is not None:
            attrs["cash_on_delivery_amount"] = self.cash_on_delivery_amount
        if self.cash_on_delivery_currency is not None:
            attrs["currency"] = self.cash_on_delivery_currency
        return attrs


def _to_float(raw: str) -> float | None:
    """Convert a localized number such as ``1.234,56`` into a float.

    With both separators present the rightmost one is the decimal separator.
    With a single separator followed by exactly three digits it is read as a
    thousands separator, which makes ``1.234`` mean 1234 and ``49,90`` mean
    49.9 - the two forms DHL is actually likely to send.
    """
    if "," in raw and "." in raw:
        thousands = "." if raw.rfind(",") > raw.rfind(".") else ","
        raw = raw.replace(thousands, "")
    elif (separator := "," if "," in raw else "." if "." in raw else None) and len(
        raw.rsplit(separator, 1)[1]
    ) == 3:
        raw = raw.replace(separator, "")
    try:
        return float(raw.replace(",", "."))
    except ValueError:  # pragma: no cover - guarded by the regex
        return None


def _parse_amount(criteria: Any) -> tuple[float | None, str | None]:
    """Parse ``serviceCriteria`` into an amount and an ISO currency code.

    The field is a free-form string in the spec, so both ``49,90 EUR`` and
    ``EUR 49.90`` have to work, and anything unparseable yields ``None``.
    """
    if not isinstance(criteria, str) or not criteria.strip():
        return None, None

    for pattern in (_AMOUNT_AFTER, _AMOUNT_BEFORE):
        if (match := pattern.search(criteria)) is None:
            continue
        if (amount := _to_float(match.group("amount"))) is None:
            return None, None
        currency = match.group("currency")
        return amount, _CURRENCY_SYMBOLS.get(currency, currency)

    return None, None


def extract_features(data: dict[str, Any] | None) -> ShipmentFeatures:
    """Derive the delivery features of a shipment payload."""
    if not data:
        return ShipmentFeatures()

    services: list[str] = []
    raw: list[str] = []
    amount: float | None = None
    currency: str | None = None

    def _add(key: str) -> None:
        if key not in services:
            services.append(key)

    # 1. Structured value added services.
    details = data.get("details")
    details = details if isinstance(details, dict) else {}
    vas = details.get("valueAddedServices")
    entries = vas.get("services") if isinstance(vas, dict) else None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("serviceFlag") is False:
            continue
        service_type = entry.get("serviceType")
        if not isinstance(service_type, str):
            continue
        if (key := VAS_TYPE_MAP.get(service_type)) is not None:
            _add(key)
            if key == SERVICE_CASH_ON_DELIVERY and amount is None:
                amount, currency = _parse_amount(entry.get("serviceCriteria"))
        elif service_type not in raw:
            # An enum value DHL added after OpenAPI 1.5.6 - pass it through.
            raw.append(service_type)

    # 2. The top level return flag.
    if data.get("returnFlag") is True:
        _add(SERVICE_RETURN)

    # 3. Free text, for everything the enum cannot express.
    product = details.get("product")
    product = product if isinstance(product, dict) else {}
    for text in (product.get("productName"), product.get("deliveryMethodRemark")):
        if not isinstance(text, str):
            continue
        for fragment in _FRAGMENT_SPLIT.split(text):
            cleaned = fragment.strip()
            if not cleaned:
                continue
            normalised = _normalise(cleaned)
            for key, patterns in TEXT_PATTERNS:
                if any(pattern in normalised for pattern in patterns):
                    _add(key)
                    break
            else:
                if cleaned not in raw:
                    raw.append(cleaned)

    return ShipmentFeatures(
        services=tuple(services),
        services_raw=tuple(raw),
        cash_on_delivery_amount=amount,
        cash_on_delivery_currency=currency,
    )
