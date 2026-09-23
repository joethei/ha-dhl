"""Tests for the events derived from comparing two API payloads."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.dhl_tracking.const import (
    DOMAIN,
    EVENT_DELIVERY_CHANGED,
    EVENT_DELIVERY_OVERDUE,
    EVENT_PROOF_OF_DELIVERY_AVAILABLE,
    EVENT_REROUTE_AVAILABLE,
    EVENT_SCAN_ADDED,
    SERVICE_ADD_SHIPMENT,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import TRACKING_NUMBER, shipment_payload

SCAN_ENTITY = "event.testpaket_tracking_scan"


def scan(timestamp: str, status: str, code: str = "transit", **extra) -> dict:
    """Return one entry of the events list, modelled on a real shipment."""
    entry = {"timestamp": timestamp, "status": status, "statusCode": code}
    entry.update(extra)
    return entry


def with_events(*events: dict, **kwargs) -> dict:
    """Return a payload carrying the given event history."""
    data = shipment_payload(TRACKING_NUMBER, **kwargs)
    data["events"] = list(events)
    return data


async def repoll(hass: HomeAssistant, entry, responses: dict, data: dict) -> None:
    """Feed a new payload through a forced refresh."""
    responses[TRACKING_NUMBER] = data
    coordinator = entry.runtime_data.coordinator
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def setup_one(hass: HomeAssistant, responses: dict, data: dict):
    """Set up a single tracked shipment with the given first payload."""
    responses[TRACKING_NUMBER] = data
    entry = build_config_entry(
        shipments=[{"tracking_number": TRACKING_NUMBER, "name": "Testpaket"}]
    )
    await setup_integration(hass, entry)
    return entry


# --- tracking scans -------------------------------------------------------------


async def test_scan_added_for_each_new_event(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The granularity the five status codes hide becomes visible."""
    first = with_events(
        scan("2026-09-22T10:44:00", "VA", "pre-transit"),
        scan("2026-09-22T19:01:00", "AA"),
    )
    entry = await setup_one(hass, shipment_responses, first)
    events = async_capture_events(hass, EVENT_SCAN_ADDED)

    await repoll(
        hass,
        entry,
        shipment_responses,
        with_events(
            scan("2026-09-22T10:44:00", "VA", "pre-transit"),
            scan("2026-09-22T19:01:00", "AA"),
            scan(
                "2026-09-23T00:38:00",
                "EE",
                description="In der Region des Empfängers angekommen.",
                location={
                    "address": {"addressLocality": "Bremen GVZ", "countryCode": "DE"}
                },
            ),
            scan("2026-09-23T08:24:00", "PO", statusDetailed="SRTED_NRQRD_PO"),
        ),
    )

    # Only the two new scans, oldest first.
    assert [event.data["status"] for event in events] == ["EE", "PO"]
    assert events[0].data["location"] == "Bremen GVZ, DE"
    assert events[0].data["description"] == "In der Region des Empfängers angekommen."
    assert events[0].data["tracking_number"] == TRACKING_NUMBER
    assert events[0].data["name"] == "Testpaket"
    assert events[1].data["status_detailed"] == "SRTED_NRQRD_PO"
    # Timestamps carry the offset, like everywhere else.
    assert dt_util.parse_datetime(events[1].data["timestamp"]).tzinfo is not None


async def test_no_scan_events_on_the_first_payload(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Adding a shipment must not replay its whole history."""
    events = async_capture_events(hass, EVENT_SCAN_ADDED)
    await setup_one(
        hass,
        shipment_responses,
        with_events(
            scan("2026-09-22T10:44:00", "VA", "pre-transit"),
            scan("2026-09-22T19:01:00", "AA"),
            scan("2026-09-23T08:24:00", "PO"),
        ),
    )
    assert events == []


async def test_unchanged_history_fires_nothing(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Polling the same data again is not an event."""
    data = with_events(scan("2026-09-23T08:24:00", "PO"))
    entry = await setup_one(hass, shipment_responses, data)
    events = async_capture_events(hass, EVENT_SCAN_ADDED)

    await repoll(hass, entry, shipment_responses, data)
    assert events == []


async def test_scan_event_entity(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The scan entity mirrors the bus event and is triggerable from the UI."""
    entry = await setup_one(
        hass, shipment_responses, with_events(scan("2026-09-22T19:01:00", "AA"))
    )
    assert hass.states.get(SCAN_ENTITY).state == "unknown"

    await repoll(
        hass,
        entry,
        shipment_responses,
        with_events(
            scan("2026-09-22T19:01:00", "AA"),
            scan("2026-09-23T08:24:00", "PO"),
        ),
    )

    state = hass.states.get(SCAN_ENTITY)
    assert state.attributes["event_type"] == "transit"
    assert state.attributes["status"] == "PO"
    assert state.attributes["tracking_number"] == TRACKING_NUMBER
    # The status entity is untouched: the status code did not change.
    assert hass.states.get("event.testpaket_shipment_status").state == "unknown"


async def test_scan_entity_created_and_removed_with_the_shipment(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The second event entity follows the same runtime lifecycle."""
    entry = build_config_entry(shipments=[])
    await setup_integration(hass, entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {"tracking_number": TRACKING_NUMBER, "name": "Testpaket"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(SCAN_ENTITY) is not None
    assert hass.states.get("event.testpaket_shipment_status") is not None


# --- delivery forecast ----------------------------------------------------------


async def test_delivery_changed_on_a_moved_window(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The case that started this: the window moved by two hours."""
    day = dt_util.now().date().isoformat()
    entry = await setup_one(
        hass,
        shipment_responses,
        shipment_payload(
            TRACKING_NUMBER,
            estimated_delivery=day,
            delivery_time_frame={
                "estimatedFrom": f"{day}T13:20:00",
                "estimatedThrough": f"{day}T14:50:00",
            },
        ),
    )
    events = async_capture_events(hass, EVENT_DELIVERY_CHANGED)

    await repoll(
        hass,
        entry,
        shipment_responses,
        shipment_payload(
            TRACKING_NUMBER,
            estimated_delivery=day,
            delivery_time_frame={
                "estimatedFrom": f"{day}T14:30:00",
                "estimatedThrough": f"{day}T16:00:00",
            },
        ),
    )

    assert len(events) == 1
    data = events[0].data
    assert dt_util.parse_datetime(data["old_from"]).hour == 13
    assert dt_util.parse_datetime(data["new_from"]).hour == 14
    assert dt_util.parse_datetime(data["new_through"]).hour == 16
    assert data["old_date"] == data["new_date"] == day


async def test_delivery_changed_on_a_moved_day(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A shipment pushed to the next day reports the new date."""
    today = dt_util.now().date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    entry = await setup_one(
        hass,
        shipment_responses,
        shipment_payload(TRACKING_NUMBER, estimated_delivery=today.isoformat()),
    )
    events = async_capture_events(hass, EVENT_DELIVERY_CHANGED)

    await repoll(
        hass,
        entry,
        shipment_responses,
        shipment_payload(TRACKING_NUMBER, estimated_delivery=tomorrow),
    )

    assert len(events) == 1
    assert events[0].data["old_date"] == today.isoformat()
    assert events[0].data["new_date"] == tomorrow


async def test_unchanged_forecast_fires_nothing(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """An identical forecast is not a change."""
    day = dt_util.now().date().isoformat()
    data = shipment_payload(TRACKING_NUMBER, estimated_delivery=day)
    entry = await setup_one(hass, shipment_responses, data)
    events = async_capture_events(hass, EVENT_DELIVERY_CHANGED)

    await repoll(hass, entry, shipment_responses, data)
    assert events == []


# --- overdue ---------------------------------------------------------------------


async def test_delivery_overdue(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A forecast that passed without delivery fires exactly once."""
    past = dt_util.now() - timedelta(hours=4)
    frame = {
        "estimatedFrom": past.replace(tzinfo=None).isoformat(),
        "estimatedThrough": (past + timedelta(minutes=30))
        .replace(tzinfo=None)
        .isoformat(),
    }
    events = async_capture_events(hass, EVENT_DELIVERY_OVERDUE)
    entry = await setup_one(
        hass,
        shipment_responses,
        shipment_payload(
            TRACKING_NUMBER, estimated_delivery=None, delivery_time_frame=frame
        ),
    )

    assert len(events) == 1
    assert events[0].data["tracking_number"] == TRACKING_NUMBER
    assert dt_util.parse_datetime(events[0].data["expected_through"]) is not None

    # Polling again does not repeat it.
    await repoll(
        hass,
        entry,
        shipment_responses,
        shipment_payload(
            TRACKING_NUMBER, estimated_delivery=None, delivery_time_frame=frame
        ),
    )
    assert len(events) == 1


async def test_overdue_fires_again_after_a_new_forecast(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A rescheduled forecast that is missed again is reported again."""

    def frame(hours_ago: float) -> dict:
        start = dt_util.now() - timedelta(hours=hours_ago)
        return {
            "estimatedFrom": start.replace(tzinfo=None).isoformat(),
            "estimatedThrough": (start + timedelta(minutes=30))
            .replace(tzinfo=None)
            .isoformat(),
        }

    events = async_capture_events(hass, EVENT_DELIVERY_OVERDUE)
    entry = await setup_one(
        hass,
        shipment_responses,
        shipment_payload(
            TRACKING_NUMBER, estimated_delivery=None, delivery_time_frame=frame(6)
        ),
    )
    assert len(events) == 1

    await repoll(
        hass,
        entry,
        shipment_responses,
        shipment_payload(
            TRACKING_NUMBER, estimated_delivery=None, delivery_time_frame=frame(3)
        ),
    )
    assert len(events) == 2


async def test_no_overdue_inside_the_grace_period(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The courier is allowed to run an hour late."""
    start = dt_util.now() - timedelta(hours=1)
    events = async_capture_events(hass, EVENT_DELIVERY_OVERDUE)
    await setup_one(
        hass,
        shipment_responses,
        shipment_payload(
            TRACKING_NUMBER,
            estimated_delivery=None,
            delivery_time_frame={
                "estimatedFrom": start.replace(tzinfo=None).isoformat(),
                "estimatedThrough": (start + timedelta(minutes=30))
                .replace(tzinfo=None)
                .isoformat(),
            },
        ),
    )
    assert events == []


async def test_delivered_shipment_is_never_overdue(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Arrived is arrived, however late."""
    past = dt_util.now() - timedelta(days=2)
    events = async_capture_events(hass, EVENT_DELIVERY_OVERDUE)
    await setup_one(
        hass,
        shipment_responses,
        shipment_payload(
            TRACKING_NUMBER,
            status="Delivered",
            status_code="delivered",
            estimated_delivery=None,
            delivery_time_frame={
                "estimatedFrom": past.replace(tzinfo=None).isoformat(),
                "estimatedThrough": (past + timedelta(minutes=30))
                .replace(tzinfo=None)
                .isoformat(),
            },
        ),
    )
    assert events == []


# --- appearing links --------------------------------------------------------------


async def test_reroute_available(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The link appearing marks the window in which rerouting is possible."""
    entry = await setup_one(hass, shipment_responses, shipment_payload(TRACKING_NUMBER))
    events = async_capture_events(hass, EVENT_REROUTE_AVAILABLE)

    data = shipment_payload(TRACKING_NUMBER)
    data["rerouteUrl"] = "https://www.dhl.de/reroute?piece=123"
    await repoll(hass, entry, shipment_responses, data)

    assert len(events) == 1
    assert events[0].data["reroute_url"] == "https://www.dhl.de/reroute?piece=123"

    # Still present on the next poll -> not a new event.
    await repoll(hass, entry, shipment_responses, data)
    assert len(events) == 1


async def test_proof_of_delivery_available(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The proof of delivery link is announced once."""
    entry = await setup_one(hass, shipment_responses, shipment_payload(TRACKING_NUMBER))
    events = async_capture_events(hass, EVENT_PROOF_OF_DELIVERY_AVAILABLE)

    data = shipment_payload(TRACKING_NUMBER, status_code="delivered")
    data["details"]["proofOfDelivery"] = {
        "documentUrl": "https://webpod.dhl.com/pod?token=abc"
    }
    await repoll(hass, entry, shipment_responses, data)

    assert len(events) == 1
    assert (
        events[0].data["proof_of_delivery_url"]
        == "https://webpod.dhl.com/pod?token=abc"
    )


async def test_reroute_announced_for_a_shipment_added_at_runtime(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A number added while rerouting is already possible still gets told."""
    data = shipment_payload(TRACKING_NUMBER)
    data["rerouteUrl"] = "https://www.dhl.de/reroute?piece=123"
    shipment_responses[TRACKING_NUMBER] = data

    entry = build_config_entry(shipments=[])
    await setup_integration(hass, entry)
    events = async_capture_events(hass, EVENT_REROUTE_AVAILABLE)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {"tracking_number": TRACKING_NUMBER},
        blocking=True,
    )
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1


async def test_no_link_events_on_a_restart(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Restoring a known shipment from the store replays nothing."""
    data = shipment_payload(TRACKING_NUMBER)
    data["rerouteUrl"] = "https://www.dhl.de/reroute?piece=123"
    events = async_capture_events(hass, EVENT_REROUTE_AVAILABLE)
    await setup_one(hass, shipment_responses, data)

    assert events == []
