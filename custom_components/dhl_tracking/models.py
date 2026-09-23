"""Data model and validation helpers for the DHL Tracking integration."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Self

from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTO_REMOVE_DELIVERED_DAYS,
    CONF_CREATED_AT,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_POLL_DELIVERED,
    CONF_RECIPIENT_POSTAL_CODE,
    CONF_SCAN_INTERVAL,
    CONF_SHIPMENTS,
    CONF_TRACKING_NUMBER,
    CONF_TRACKING_NUMBERS,
    DEFAULT_AUTO_REMOVE_DELIVERED_DAYS,
    DEFAULT_LANGUAGE,
    DEFAULT_POLL_DELIVERED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_AUTO_REMOVE_DELIVERED_DAYS,
    MAX_NAME_LENGTH,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    POSTAL_CODE_PATTERN,
    TRACKING_NUMBER_PATTERN,
)

_TRACKING_NUMBER_RE = re.compile(TRACKING_NUMBER_PATTERN)
_POSTAL_CODE_RE = re.compile(POSTAL_CODE_PATTERN)


class ShipmentValidationError(ServiceValidationError):
    """Raised when user supplied shipment data is not acceptable.

    Subclasses ``ServiceValidationError`` so that service calls surface a
    translated, user-facing message instead of a stack trace. The
    ``translation_key`` is also reused as the config/options flow error key.
    """

    def __init__(self, translation_key: str, **placeholders: str) -> None:
        """Initialize the error."""
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=translation_key,
            translation_placeholders=placeholders or None,
        )
        self.error_key = translation_key


def normalize_tracking_number(value: Any) -> str:
    """Return a cleaned tracking number or raise ``ShipmentValidationError``.

    Whitespace anywhere in the number is removed - DHL prints parcel numbers in
    groups of digits and users copy them that way.
    """
    if not isinstance(value, str):
        raise ShipmentValidationError("invalid_tracking_number")

    cleaned = "".join(value.split()).upper()
    if not cleaned:
        raise ShipmentValidationError("empty_tracking_number")
    if not _TRACKING_NUMBER_RE.match(cleaned):
        raise ShipmentValidationError("invalid_tracking_number")
    return cleaned


def normalize_name(value: Any) -> str | None:
    """Return a cleaned display name, or ``None`` when not supplied."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ShipmentValidationError("invalid_name")

    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ShipmentValidationError("invalid_name")
    return cleaned


def normalize_postal_code(value: Any) -> str | None:
    """Return a cleaned recipient postal code, or ``None`` when not supplied."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ShipmentValidationError("invalid_postal_code")

    cleaned = " ".join(value.split()).upper()
    if not cleaned:
        return None
    if not _POSTAL_CODE_RE.match(cleaned):
        raise ShipmentValidationError("invalid_postal_code")
    return cleaned


@dataclass(frozen=True, slots=True)
class Shipment:
    """A tracked shipment as persisted in the config entry options."""

    tracking_number: str
    name: str | None = None
    recipient_postal_code: str | None = None
    created_at: str | None = None

    @classmethod
    def create(
        cls,
        tracking_number: Any,
        name: Any = None,
        recipient_postal_code: Any = None,
        created_at: datetime | None = None,
    ) -> Self:
        """Build a validated shipment from raw user input."""
        return cls(
            tracking_number=normalize_tracking_number(tracking_number),
            name=normalize_name(name),
            recipient_postal_code=normalize_postal_code(recipient_postal_code),
            created_at=(created_at or dt_util.utcnow()).isoformat(),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Restore a shipment from its persisted representation."""
        return cls(
            tracking_number=str(data[CONF_TRACKING_NUMBER]),
            name=data.get(CONF_NAME) or None,
            recipient_postal_code=data.get(CONF_RECIPIENT_POSTAL_CODE) or None,
            created_at=data.get(CONF_CREATED_AT) or None,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the persisted representation."""
        return {
            CONF_TRACKING_NUMBER: self.tracking_number,
            CONF_NAME: self.name,
            CONF_RECIPIENT_POSTAL_CODE: self.recipient_postal_code,
            CONF_CREATED_AT: self.created_at,
        }

    @property
    def display_name(self) -> str:
        """Return the name shown to the user."""
        return self.name or f"DHL {self.tracking_number}"


@dataclass(frozen=True, slots=True)
class DhlOptions:
    """Typed view on the config entry options."""

    shipments: tuple[Shipment, ...] = ()
    scan_interval: int = DEFAULT_SCAN_INTERVAL
    language: str = DEFAULT_LANGUAGE
    poll_delivered: bool = DEFAULT_POLL_DELIVERED
    auto_remove_delivered_days: int = DEFAULT_AUTO_REMOVE_DELIVERED_DAYS

    @classmethod
    def from_mapping(cls, options: Mapping[str, Any]) -> Self:
        """Build options from the stored config entry options mapping."""
        shipments = tuple(
            Shipment.from_dict(item) for item in options.get(CONF_SHIPMENTS, [])
        )
        scan_interval = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        try:
            scan_interval = int(scan_interval)
        except (TypeError, ValueError):
            scan_interval = DEFAULT_SCAN_INTERVAL
        scan_interval = min(max(scan_interval, MIN_SCAN_INTERVAL), MAX_SCAN_INTERVAL)

        auto_remove = options.get(
            CONF_AUTO_REMOVE_DELIVERED_DAYS, DEFAULT_AUTO_REMOVE_DELIVERED_DAYS
        )
        try:
            auto_remove = int(auto_remove)
        except (TypeError, ValueError):
            auto_remove = DEFAULT_AUTO_REMOVE_DELIVERED_DAYS
        auto_remove = min(max(auto_remove, 0), MAX_AUTO_REMOVE_DELIVERED_DAYS)

        language = options.get(CONF_LANGUAGE) or DEFAULT_LANGUAGE
        return cls(
            shipments=shipments,
            scan_interval=scan_interval,
            language=str(language),
            poll_delivered=bool(
                options.get(CONF_POLL_DELIVERED, DEFAULT_POLL_DELIVERED)
            ),
            auto_remove_delivered_days=auto_remove,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the mapping to persist in the config entry options."""
        return {
            CONF_SHIPMENTS: [shipment.as_dict() for shipment in self.shipments],
            CONF_SCAN_INTERVAL: self.scan_interval,
            CONF_LANGUAGE: self.language,
            CONF_POLL_DELIVERED: self.poll_delivered,
            CONF_AUTO_REMOVE_DELIVERED_DAYS: self.auto_remove_delivered_days,
        }

    def with_shipments(self, shipments: Iterable[Shipment]) -> Self:
        """Return a copy with a replaced shipment list."""
        return type(self)(
            shipments=tuple(shipments),
            scan_interval=self.scan_interval,
            language=self.language,
            poll_delivered=self.poll_delivered,
            auto_remove_delivered_days=self.auto_remove_delivered_days,
        )

    def get(self, tracking_number: str) -> Shipment | None:
        """Return the shipment with the given tracking number, if tracked."""
        for shipment in self.shipments:
            if shipment.tracking_number == tracking_number:
                return shipment
        return None


def parse_legacy_tracking_numbers(value: Any) -> list[str]:
    """Normalise the legacy ``tracking_numbers`` value into a list.

    Version 1 config entries stored the numbers either as a list (created via
    the config flow) or as the raw comma separated string the user typed.
    """
    if value is None:
        return []

    if isinstance(value, str):
        raw_items: list[str] = re.split(r"[,;\n]", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        return []

    numbers: list[str] = []
    for item in raw_items:
        cleaned = "".join(str(item).split()).upper()
        if not cleaned:
            continue
        if not _TRACKING_NUMBER_RE.match(cleaned):
            continue
        if cleaned not in numbers:
            numbers.append(cleaned)
    return numbers


def migrate_legacy_options(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert a legacy ``tracking_numbers`` value into shipment records."""
    now = dt_util.utcnow().isoformat()
    return [
        Shipment(
            tracking_number=number,
            name=None,
            recipient_postal_code=None,
            created_at=now,
        ).as_dict()
        for number in parse_legacy_tracking_numbers(data.get(CONF_TRACKING_NUMBERS))
    ]
