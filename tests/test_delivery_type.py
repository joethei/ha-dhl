"""Tests for the delivery type and the summary binary sensors.

The scan sequences are taken from real DHL Paket shipments: two parcels
delivered to a drop-off location and one collected from a Packstation.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.dhl_tracking.const import EVENT_STATUS_CHANGED
from custom_components.dhl_tracking.coordinator import pickup_wait
from custom_components.dhl_tracking.pickup import delivery_type, drop_off_planned
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import OTHER_TRACKING_NUMBER, TRACKING_NUMBER, shipment_payload
from .test_pickup import on_the_way_status, ready_status

EXPECTED = "binary_sensor.dhl_tracking_delivery_expected_today"
PICKUP = "binary_sensor.dhl_tracking_pickup_waiting"

LOADED = {
    "timestamp": "2026-10-06T08:38:00",
    "statusCode": "transit",
    "status": "PO",
    "statusDetailed": "SRTED_NRQRD_PO",
    "description": "Die Sendung wurde in das Zustellfahrzeug geladen.",
}
DROP_OFF_ANNOUNCED = {
    "timestamp": "2026-10-06T14:30:00",
    "statusCode": "transit",
    "status": "PO",
    "statusDetailed": "ADVIS_PFLOC_DD",
    "description": "Für diese Sendung wurde ein Ablageort als Empfangsoption vorgemerkt.",
}
DROPPED_OFF = {
    "timestamp": "2026-10-06T15:37:00",
    "statusCode": "delivered",
    "status": "ZU",
    "statusDetailed": "DLVRD_SECPL_ZU",
    "description": "Die Sendung wurde zugestellt.",
}


def with_history(*events: dict[str, Any], number: str = TRACKING_NUMBER, **kwargs):
    """Return a payload whose status is the newest of the given events."""
    data = shipment_payload(number, **kwargs)
    data["events"] = list(reversed(events))
    data["status"] = dict(events[-1])
    return data


# --- delivery type ------------------------------------------------------------


def test_drop_off_location_is_recognised() -> None:
    """`DLVRD_SECPL` is a delivery to the drop-off location."""
    data = with_history(LOADED, DROP_OFF_ANNOUNCED, DROPPED_OFF)
    assert delivery_type(data) == "drop_off"
    assert drop_off_planned(data) is False


def test_drop_off_is_announced_before_delivery() -> None:
    """`ADVIS_PFLOC` tells about an hour ahead where the parcel will go."""
    assert drop_off_planned(with_history(LOADED)) is False
    assert drop_off_planned(with_history(LOADED, DROP_OFF_ANNOUNCED)) is True


def test_collected_parcel_is_picked_up() -> None:
    """Delivered after waiting in a Packstation means collected there."""
    collected = {**DROPPED_OFF, "statusDetailed": "DLVRD_UNKNW_ZU"}
    data = with_history(on_the_way_status(), ready_status(), collected)
    assert delivery_type(data) == "picked_up"


def test_unknown_delivery_stays_unknown() -> None:
    """Without a known code nothing is guessed - neighbour or doorstep."""
    plain = {**DROPPED_OFF, "statusDetailed": "DLVRD_UNKNW_ZU"}
    assert delivery_type(with_history(LOADED, plain)) is None
    assert delivery_type(with_history(LOADED)) is None


async def test_status_event_carries_the_delivery_type(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Automations reacting to the delivery learn where the parcel is."""
    shipment_responses[TRACKING_NUMBER] = with_history(LOADED, DROP_OFF_ANNOUNCED)
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)
    prefix = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
    assert hass.states.get(f"{prefix}_status_code").attributes["drop_off_planned"]

    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    shipment_responses[TRACKING_NUMBER] = with_history(
        LOADED, DROP_OFF_ANNOUNCED, DROPPED_OFF
    )
    coordinator = entry.runtime_data.coordinator
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert events[-1].data["delivery_type"] == "drop_off"
    attrs = hass.states.get(f"{prefix}_status_code").attributes
    assert attrs["delivery_type"] == "drop_off"
    assert attrs["drop_off_planned"] is False


# --- binary sensors -----------------------------------------------------------


async def test_delivery_expected_today(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """On for a parcel due today, off for one waiting in a Packstation."""
    today = dt_util.now().date().isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, estimated_delivery=today
    )
    # DHL keeps the day of the Packstation run in the forecast.
    waiting = shipment_payload(OTHER_TRACKING_NUMBER, estimated_delivery=today)
    waiting["status"] = ready_status()
    shipment_responses[OTHER_TRACKING_NUMBER] = waiting
    entry = build_config_entry(
        shipments=[
            {"tracking_number": TRACKING_NUMBER, "name": "Wein (Anna)"},
            {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Kabel"},
        ]
    )
    await setup_integration(hass, entry)

    expected = hass.states.get(EXPECTED)
    assert expected.state == "on"
    assert expected.attributes["shipments"] == [
        {"tracking_number": TRACKING_NUMBER, "name": "Wein (Anna)"}
    ]

    pickup = hass.states.get(PICKUP)
    assert pickup.state == "on"
    [waiting_entry] = pickup.attributes["shipments"]
    assert waiting_entry["tracking_number"] == OTHER_TRACKING_NUMBER
    assert waiting_entry["name"] == "Kabel"
    assert waiting_entry["pickup_location"] == (
        "Packstation 205, Christian-Hülsmeyer-Str. 3, 27472 Cuxhaven"
    )
    # Placed on 1 October: 7 calendar days, the first one included.
    assert waiting_entry["estimated_pickup_deadline"] == "2026-10-07"


async def test_binary_sensors_off_without_matching_parcels(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """A parcel due another day turns nothing on."""
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    assert hass.states.get(EXPECTED).state == "off"
    assert hass.states.get(PICKUP).state == "off"
    assert hass.states.get(PICKUP).attributes["shipments"] == []


async def test_delivered_parcel_is_no_longer_expected(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Once delivered, the sensor goes off even though the day is today."""
    today = dt_util.now().date().isoformat()
    shipment_responses[TRACKING_NUMBER] = with_history(
        LOADED, DROPPED_OFF, estimated_delivery=today
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    assert hass.states.get(EXPECTED).state == "off"


async def test_expected_today_follows_midnight(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    shipment_responses: dict,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Tomorrow's parcel turns the sensor on at midnight, without a poll."""
    local_now = dt_util.now()
    freezer.move_to(local_now.replace(hour=23, minute=59, second=30))
    tomorrow = (dt_util.now() + timedelta(days=1)).date().isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, estimated_delivery=tomorrow
    )
    entry = build_config_entry(
        options={"scan_interval": 86400},
        shipments=[{"tracking_number": TRACKING_NUMBER}],
    )
    await setup_integration(hass, entry)
    assert hass.states.get(EXPECTED).state == "off"

    calls = mock_api.call_count
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_api.call_count == calls
    assert hass.states.get(EXPECTED).state == "on"


# --- pickup deadline ------------------------------------------------------------


def test_pickup_wait_counts_calendar_days() -> None:
    """Placed on the 1st, the parcel may be collected until the 7th."""
    data = with_history(on_the_way_status(), ready_status())
    placed = dt_util.parse_datetime("2026-10-01T12:33:00").replace(
        tzinfo=dt_util.get_default_time_zone()
    )
    wait = pickup_wait(data, placed + timedelta(days=5))
    assert wait == {
        "waiting_since": placed.isoformat(),
        "days_waiting": 5,
        "estimated_pickup_deadline": "2026-10-07",
    }


def test_pickup_wait_uses_the_first_pickup_scan() -> None:
    """A repeated pickup scan does not restart the clock."""
    later = {**ready_status(), "timestamp": "2026-10-03T08:00:00"}
    data = with_history(ready_status(), later)
    wait = pickup_wait(data, dt_util.utcnow())
    assert wait["estimated_pickup_deadline"] == "2026-10-07"


def test_no_pickup_wait_unless_waiting() -> None:
    """On the way, or already collected, there is no deadline."""
    assert pickup_wait(with_history(LOADED), dt_util.utcnow()) == {}
    assert (
        pickup_wait(with_history(ready_status(), DROPPED_OFF), dt_util.utcnow()) == {}
    )
