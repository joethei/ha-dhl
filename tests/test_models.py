"""Unit tests for validation, normalisation and the options model."""

from __future__ import annotations

import pytest

from custom_components.dhl_tracking.const import (
    DEFAULT_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from custom_components.dhl_tracking.models import (
    DhlOptions,
    Shipment,
    ShipmentValidationError,
    normalize_name,
    normalize_postal_code,
    normalize_tracking_number,
    parse_legacy_tracking_numbers,
)

from .const import OTHER_TRACKING_NUMBER, TRACKING_NUMBER


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (TRACKING_NUMBER, TRACKING_NUMBER),
        (f" {TRACKING_NUMBER} ", TRACKING_NUMBER),
        ("0034 0434 1234 5678 9012", TRACKING_NUMBER),
        ("jvgl1234567890", "JVGL1234567890"),
        ("1Z-999-AA1", "1Z-999-AA1"),
    ],
)
def test_normalize_tracking_number(raw: str, expected: str) -> None:
    """Whitespace is stripped and the number is upper-cased."""
    assert normalize_tracking_number(raw) == expected


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("", "empty_tracking_number"),
        ("   ", "empty_tracking_number"),
        (None, "invalid_tracking_number"),
        (12345, "invalid_tracking_number"),
        ("123", "invalid_tracking_number"),
        ("-1234", "invalid_tracking_number"),
        ("0034 0434!", "invalid_tracking_number"),
        ("X" * 40, "invalid_tracking_number"),
    ],
)
def test_normalize_tracking_number_rejects(raw: object, key: str) -> None:
    """Invalid input raises a translated validation error."""
    with pytest.raises(ShipmentValidationError) as err:
        normalize_tracking_number(raw)
    assert err.value.error_key == key


def test_normalize_name() -> None:
    """Names are collapsed and optional."""
    assert normalize_name("  Ersatz   teil ") == "Ersatz teil"
    assert normalize_name("   ") is None
    assert normalize_name(None) is None
    with pytest.raises(ShipmentValidationError):
        normalize_name("x" * 101)


def test_normalize_postal_code() -> None:
    """Postal codes are trimmed, upper-cased and optional."""
    assert normalize_postal_code(" 12345 ") == "12345"
    assert normalize_postal_code("sw1a 1aa") == "SW1A 1AA"
    assert normalize_postal_code("") is None
    with pytest.raises(ShipmentValidationError):
        normalize_postal_code("!!")


def test_shipment_roundtrip() -> None:
    """Shipments survive a serialisation round trip."""
    shipment = Shipment.create(f" {TRACKING_NUMBER} ", " Paket ", " 12345 ")
    restored = Shipment.from_dict(shipment.as_dict())
    assert restored == shipment
    assert restored.display_name == "Paket"
    assert Shipment(tracking_number=TRACKING_NUMBER).display_name == (
        f"DHL {TRACKING_NUMBER}"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        ([], []),
        ([TRACKING_NUMBER], [TRACKING_NUMBER]),
        (
            f"{TRACKING_NUMBER};{OTHER_TRACKING_NUMBER}",
            [TRACKING_NUMBER, OTHER_TRACKING_NUMBER],
        ),
        (
            f"{TRACKING_NUMBER}\n{OTHER_TRACKING_NUMBER}",
            [TRACKING_NUMBER, OTHER_TRACKING_NUMBER],
        ),
        ([TRACKING_NUMBER, TRACKING_NUMBER], [TRACKING_NUMBER]),
        ("0,0,3,4", []),
        (12345, []),
    ],
)
def test_parse_legacy_tracking_numbers(raw: object, expected: list[str]) -> None:
    """The legacy value is normalised without losing valid numbers."""
    assert parse_legacy_tracking_numbers(raw) == expected


def test_options_defaults_and_clamping() -> None:
    """Out-of-range or broken option values fall back to safe defaults."""
    assert DhlOptions.from_mapping({}) == DhlOptions(
        shipments=(), scan_interval=DEFAULT_SCAN_INTERVAL, language=DEFAULT_LANGUAGE
    )
    assert DhlOptions.from_mapping({"scan_interval": 1}).scan_interval == (
        MIN_SCAN_INTERVAL
    )
    assert DhlOptions.from_mapping({"scan_interval": 10**9}).scan_interval == (
        MAX_SCAN_INTERVAL
    )
    assert DhlOptions.from_mapping({"scan_interval": "nonsense"}).scan_interval == (
        DEFAULT_SCAN_INTERVAL
    )
    assert DhlOptions.from_mapping({"language": None}).language == DEFAULT_LANGUAGE


def test_options_lookup_and_replacement() -> None:
    """Shipments can be looked up and replaced without touching the rest."""
    options = DhlOptions(
        shipments=(Shipment(tracking_number=TRACKING_NUMBER),), scan_interval=600
    )
    assert options.get(TRACKING_NUMBER) is not None
    assert options.get(OTHER_TRACKING_NUMBER) is None

    replaced = options.with_shipments([Shipment(tracking_number=OTHER_TRACKING_NUMBER)])
    assert replaced.scan_interval == 600
    assert replaced.get(TRACKING_NUMBER) is None
