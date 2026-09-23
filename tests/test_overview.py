"""Tests for the per config entry summary sensors and the name attribute."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dhl_tracking.const import DOMAIN, SERVICE_ADD_SHIPMENT
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import OTHER_TRACKING_NUMBER, TRACKING_NUMBER, shipment_payload

OPEN = "sensor.dhl_tracking_open_shipments"
NEXT = "sensor.dhl_tracking_next_delivery"


async def test_open_shipments_counts_undelivered(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Delivered shipments do not count towards the open total."""
    shipment_responses[OTHER_TRACKING_NUMBER] = shipment_payload(
        OTHER_TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    entry = build_config_entry(
        shipments=[
            {"tracking_number": TRACKING_NUMBER, "name": "Ersatzteil"},
            {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Buch"},
        ]
    )
    await setup_integration(hass, entry)

    state = hass.states.get(OPEN)
    assert state.state == "1"

    shipments = state.attributes["shipments"]
    assert len(shipments) == 1
    entry_data = shipments[0]
    assert entry_data["tracking_number"] == TRACKING_NUMBER
    assert entry_data["name"] == "Ersatzteil"
    assert entry_data["status_code"] == "transit"
    assert entry_data["description"] == "The shipment is on its way."
    assert entry_data["signature_required"] is False
    assert entry_data["services"] == []
    assert set(entry_data) == {
        "tracking_number",
        "name",
        "status_code",
        "status",
        "description",
        "estimated_delivery",
        "estimated_delivery_date",
        "time_frame_from",
        "time_frame_through",
        "signature_required",
        "id_required",
        "services",
        "customer_reference",
        "next_steps",
    }


async def test_open_shipments_reflects_services(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The overview carries the derived delivery features."""
    data = shipment_payload(TRACKING_NUMBER)
    data["details"]["product"]["productName"] = "DHL PAKET, Empfängerunterschrift"
    shipment_responses[TRACKING_NUMBER] = data
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    shipments = hass.states.get(OPEN).attributes["shipments"]
    assert shipments[0]["signature_required"] is True
    assert shipments[0]["services"] == ["signature"]


async def test_open_shipments_updates_at_runtime(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Adding a shipment bumps the counter without a restart."""
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(OPEN).state == "1"

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {"tracking_number": OTHER_TRACKING_NUMBER},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get(OPEN).state == "2"


async def test_open_shipments_is_zero_without_shipments(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """The summary exists even when nothing is tracked."""
    entry = build_config_entry(shipments=[])
    await setup_integration(hass, entry)

    state = hass.states.get(OPEN)
    assert state.state == "0"
    assert state.attributes["shipments"] == []


async def test_next_delivery_picks_the_earliest_time(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The timestamp is the earliest precise delivery time across shipments."""
    today = dt_util.now().date().isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER,
        estimated_delivery=None,
        delivery_time_frame={
            "estimatedFrom": f"{today}T15:00:00",
            "estimatedThrough": f"{today}T17:00:00",
        },
    )
    shipment_responses[OTHER_TRACKING_NUMBER] = shipment_payload(
        OTHER_TRACKING_NUMBER,
        estimated_delivery=None,
        delivery_time_frame={
            "estimatedFrom": f"{today}T09:00:00",
            "estimatedThrough": f"{today}T11:00:00",
        },
    )
    entry = build_config_entry(
        shipments=[
            {"tracking_number": TRACKING_NUMBER, "name": "Spaet"},
            {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Frueh"},
        ]
    )
    await setup_integration(hass, entry)

    state = hass.states.get(NEXT)
    assert dt_util.parse_datetime(state.state) == dt_util.parse_datetime(
        f"{today}T09:00:00"
    ).replace(tzinfo=dt_util.get_default_time_zone())
    assert state.attributes["name"] == "Frueh"
    assert state.attributes["tracking_number"] == OTHER_TRACKING_NUMBER


async def test_next_delivery_without_a_precise_time(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """With day-only forecasts the timestamp is empty, the day is not."""
    tomorrow = (dt_util.now() + timedelta(days=1)).date().isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, estimated_delivery=tomorrow
    )
    entry = build_config_entry(
        shipments=[{"tracking_number": TRACKING_NUMBER, "name": "Paket"}]
    )
    await setup_integration(hass, entry)

    state = hass.states.get(NEXT)
    assert state.state == "unknown"
    assert state.attributes["earliest_date"] == tomorrow
    assert state.attributes["earliest_date_name"] == "Paket"


async def test_next_delivery_ignores_delivered(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A delivered shipment is not a future delivery."""
    today = dt_util.now().date().isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER,
        status_code="delivered",
        estimated_delivery=None,
        delivery_time_frame={
            "estimatedFrom": f"{today}T09:00:00",
            "estimatedThrough": f"{today}T11:00:00",
        },
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    assert hass.states.get(NEXT).state == "unknown"
    assert hass.states.get(OPEN).state == "0"


async def test_name_attribute_on_shipment_sensors(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The plain shipment name is available without parsing the friendly name."""
    await setup_integration(hass, mock_config_entry)

    for entity_id in ("sensor.testpaket_status_code", "sensor.testpaket_status"):
        state = hass.states.get(entity_id)
        assert state.attributes["name"] == "Testpaket"
        assert state.attributes["friendly_name"] != "Testpaket"


async def test_name_attribute_falls_back_to_the_tracking_number(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """Without a display name the tracking number based name is used."""
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    state = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_status_code")
    assert state.attributes["name"] == f"DHL {TRACKING_NUMBER}"
