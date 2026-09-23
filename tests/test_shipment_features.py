"""Tests for deriving delivery features from a tracking payload."""

from __future__ import annotations

import pytest

from custom_components.dhl_tracking.shipment_features import (
    ShipmentFeatures,
    extract_features,
)


def product(name: str, remark: str | None = None) -> dict:
    """Return a payload carrying only a product name."""
    entry: dict = {"productName": name}
    if remark is not None:
        entry["deliveryMethodRemark"] = remark
    return {"details": {"product": entry}}


def vas(*services: dict) -> dict:
    """Return a payload carrying structured value added services."""
    return {"details": {"valueAddedServices": {"services": list(services)}}}


# --- structured source is preferred -------------------------------------------


def test_structured_value_added_services_are_used() -> None:
    """The documented serviceType enum maps onto normalised keys."""
    features = extract_features(
        vas(
            {"serviceType": "bulky", "serviceFlag": True},
            {"serviceType": "gogreen"},
            {"serviceType": "priority"},
        )
    )
    assert set(features.services) == {"bulky", "gogreen", "priority"}
    assert features.signature_required is False
    assert features.id_required is False


def test_disabled_service_flag_is_ignored() -> None:
    """An explicit serviceFlag=false means the service is not booked."""
    features = extract_features(vas({"serviceType": "bulky", "serviceFlag": False}))
    assert features.services == ()


def test_unknown_service_type_is_passed_through() -> None:
    """An enum value added after OpenAPI 1.5.6 must not be dropped."""
    features = extract_features(vas({"serviceType": "quantumTeleport"}))
    assert features.services == ()
    assert features.services_raw == ("quantumTeleport",)


@pytest.mark.parametrize(
    ("criteria", "amount", "currency"),
    [
        ("49,90 EUR", 49.90, "EUR"),
        ("49.90 EUR", 49.90, "EUR"),
        ("EUR 49.90", 49.90, "EUR"),
        ("49,90 €", 49.90, "EUR"),
        ("$ 12.50", 12.50, "USD"),
        ("1.234,56 EUR", 1234.56, "EUR"),
        ("1.234 EUR", 1234.0, "EUR"),
        ("5 EUR", 5.0, "EUR"),
        ("", None, None),
        ("Nachnahmebetrag unbekannt", None, None),
        (None, None, None),
    ],
)
def test_cash_on_delivery_amount(
    criteria: str | None, amount: float | None, currency: str | None
) -> None:
    """The free-form serviceCriteria is parsed defensively."""
    features = extract_features(
        vas({"serviceType": "cashOnDelivery", "serviceCriteria": criteria})
    )
    assert "cash_on_delivery" in features.services
    assert features.cash_on_delivery_amount == amount
    assert features.cash_on_delivery_currency == currency
    # Cash on delivery is handed over in person.
    assert features.signature_required is True


# --- free text fallback --------------------------------------------------------


@pytest.mark.parametrize(
    ("product_name", "expected"),
    [
        # The live example from the user's shipment.
        ("DHL PAKET, Empfängerunterschrift", {"signature"}),
        ("dhl paket, empfängerunterschrift", {"signature"}),
        ("DHL PAKET, EMPFÄNGERUNTERSCHRIFT", {"signature"}),
        ("DHL Paket, Empfaengerunterschrift", {"signature"}),
        ("DHL Paket, Ident-Check", {"ident_check"}),
        ("DHL Paket, IdentCheck", {"ident_check"}),
        ("DHL Paket, Postident", {"ident_check"}),
        ("DHL Paket, Alterssichtprüfung 18", {"age_check"}),
        ("DHL Paket, Nachnahme", {"cash_on_delivery"}),
        ("DHL Paket, Wunschtag", {"preferred_day"}),
        ("DHL Paket, Wunschort", {"preferred_location"}),
        ("DHL Paket, Abstellgenehmigung", {"preferred_location"}),
        ("DHL Paket, Wunschnachbar", {"preferred_neighbour"}),
        ("DHL Paket, Keine Nachbarschaftsabgabe", {"no_neighbour_delivery"}),
        ("DHL Paket, Eigenhändig", {"no_neighbour_delivery"}),
        ("DHL Paket Sperrgut", {"bulky"}),
        ("DHL Retoure", {"return"}),
        ("Worldwide Priority, Signature", {"signature"}),
        # Several at once.
        (
            "DHL PAKET, Empfängerunterschrift, Nachnahme, Wunschtag",
            {"signature", "cash_on_delivery", "preferred_day"},
        ),
        # Nothing special.
        ("DHL Paket", set()),
    ],
)
def test_product_text_is_parsed(product_name: str, expected: set[str]) -> None:
    """Features DHL only ships as free text are parsed case-insensitively."""
    features = extract_features(product(product_name))
    assert set(features.services) == expected


def test_no_neighbour_wins_over_preferred_neighbour() -> None:
    """The negative wording must not be read as "Wunschnachbar"."""
    features = extract_features(product("DHL Paket, Keine Nachbarschaftsabgabe"))
    assert features.services == ("no_neighbour_delivery",)
    assert "preferred_neighbour" not in features.services


def test_unknown_product_fragments_are_kept_raw() -> None:
    """Nothing is silently dropped."""
    features = extract_features(product("DHL PAKET, Empfängerunterschrift"))
    assert features.services == ("signature",)
    assert features.services_raw == ("DHL PAKET",)


def test_delivery_method_remark_is_parsed_too() -> None:
    """The second free-text product field is evaluated as well."""
    features = extract_features(product("DHL Paket", remark="Alterssichtprüfung 16"))
    assert "age_check" in features.services


# --- derived booleans ----------------------------------------------------------


@pytest.mark.parametrize(
    ("product_name", "signature", "identity"),
    [
        ("DHL PAKET, Empfängerunterschrift", True, False),
        ("DHL Paket, Ident-Check", True, True),
        ("DHL Paket, Alterssichtprüfung 18", True, True),
        ("DHL Paket, Nachnahme", True, False),
        ("DHL Paket, Wunschort", False, False),
        ("DHL Paket", False, False),
    ],
)
def test_signature_and_id_flags(
    product_name: str, signature: bool, identity: bool
) -> None:
    """Handover requirements are derived from the recognised services."""
    features = extract_features(product(product_name))
    assert features.signature_required is signature
    assert features.id_required is identity


def test_return_flag_is_a_service() -> None:
    """The documented top level returnFlag becomes a service key."""
    assert "return" in extract_features({"returnFlag": True}).services
    assert extract_features({"returnFlag": False}).services == ()


def test_structured_and_text_sources_combine() -> None:
    """Both sources contribute to the same list, without duplicates."""
    payload = {
        "returnFlag": True,
        "details": {
            "product": {"productName": "DHL PAKET, Empfängerunterschrift, Sperrgut"},
            "valueAddedServices": {"services": [{"serviceType": "bulky"}]},
        },
    }
    features = extract_features(payload)
    assert features.services.count("bulky") == 1
    assert set(features.services) == {"bulky", "return", "signature"}


@pytest.mark.parametrize("payload", [None, {}, {"details": None}, {"details": {}}])
def test_missing_data_is_handled(payload: dict | None) -> None:
    """A payload without any of the fields yields empty features."""
    assert extract_features(payload) == ShipmentFeatures()


def test_attributes_shape() -> None:
    """The attribute dict only carries keys that have a value."""
    plain = extract_features(product("DHL Paket")).as_attributes()
    assert plain == {
        "services": [],
        "signature_required": False,
        "id_required": False,
        # The base product name is not a service, but it is handed through.
        "services_raw": ["DHL Paket"],
    }

    full = extract_features(
        vas({"serviceType": "cashOnDelivery", "serviceCriteria": "49,90 EUR"})
    ).as_attributes()
    assert full["cash_on_delivery_amount"] == 49.90
    assert full["currency"] == "EUR"
