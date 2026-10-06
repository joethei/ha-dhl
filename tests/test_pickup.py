"""Tests for parcels waiting in a Packstation or at a pickup point.

The payloads are modelled on real responses for a DHL Paket that was sent to
a Packstation: `statusCode` stays `transit` throughout, only
`statusDetailed` and an HTML link in the description tell the cases apart.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.dhl_tracking.const import (
    EVENT_SCAN_ADDED,
    STATUS_CODE_READY_FOR_PICKUP,
    STATUS_CODE_TRANSIT,
)
from custom_components.dhl_tracking.coordinator import (
    ShipmentPriority,
    derive_status_code,
)
from custom_components.dhl_tracking.pickup import (
    is_ready_for_pickup,
    pickup_location,
    plain_text,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import TRACKING_NUMBER, shipment_payload

READY_DESCRIPTION = (
    "Die Sendung liegt in der <a href='https://www.dhl.de/de/privatkunden/"
    "dhl-standorte-finden.html?address=27472:205&preferPackstation=true' "
    "class='arrowLink' target='_blank'><span class='arrow'></span>Packstation "
    "205, Christian-Hülsmeyer-Str. 3, 27472 Cuxhaven</a> zur Abholung bereit."
)
READY_PLAIN = (
    "Die Sendung liegt in der Packstation 205, Christian-Hülsmeyer-Str. 3, "
    "27472 Cuxhaven zur Abholung bereit."
)


def ready_status() -> dict[str, Any]:
    """Return the status block of a parcel placed in a Packstation."""
    return {
        "timestamp": "2026-10-01T12:33:00",
        "location": {"address": {"addressLocality": "Cuxhaven, Deutschland"}},
        "statusCode": "transit",
        "status": "LA",
        "statusDetailed": "HLDCC_LDPCK_LA",
        "description": READY_DESCRIPTION,
        "remark": READY_DESCRIPTION,
    }


def on_the_way_status() -> dict[str, Any]:
    """Return the status block of a parcel on its way to a Packstation."""
    return {
        "timestamp": "2026-10-06T08:34:00",
        "statusCode": "transit",
        "status": "PO",
        "statusDetailed": "LDTMV_PCKST_PO",
        "description": "Die Sendung befindet sich auf dem Weg zur Packstation.",
    }


def ready_payload() -> dict[str, Any]:
    """Return a full payload for a parcel waiting in a Packstation.

    DHL keeps the delivery day of the Packstation run in the payload.
    """
    data = shipment_payload(
        TRACKING_NUMBER, estimated_delivery=dt_util.now().date().isoformat()
    )
    data["status"] = ready_status()
    data["events"] = [ready_status(), on_the_way_status()]
    return data


# --- helpers ------------------------------------------------------------------


def test_ready_for_pickup_is_detected_from_status_detailed() -> None:
    """Only the `HLDCC` group counts, not the way to the Packstation."""
    assert is_ready_for_pickup(ready_status()) is True
    assert is_ready_for_pickup(on_the_way_status()) is False
    assert is_ready_for_pickup(None) is False


def test_collected_parcel_is_not_ready_for_pickup() -> None:
    """Once collected DHL reports `delivered`, which wins."""
    status = {**ready_status(), "statusCode": "delivered"}
    assert is_ready_for_pickup(status) is False


def test_pickup_location_is_parsed_from_the_link() -> None:
    """Label from the link text, postal code and locker from the URL."""
    assert pickup_location(ready_status()) == {
        "label": "Packstation 205, Christian-Hülsmeyer-Str. 3, 27472 Cuxhaven",
        "name": "Packstation 205",
        "address": "Christian-Hülsmeyer-Str. 3, 27472 Cuxhaven",
        "url": (
            "https://www.dhl.de/de/privatkunden/dhl-standorte-finden.html"
            "?address=27472:205&preferPackstation=true"
        ),
        "postal_code": "27472",
        "locker_id": "205",
    }


def test_status_without_link_has_no_pickup_location() -> None:
    """The way to the Packstation names no Packstation yet."""
    assert pickup_location(on_the_way_status()) is None


def test_plain_text_strips_markup() -> None:
    """HTML becomes readable text; plain text and non-strings pass through."""
    assert plain_text(READY_DESCRIPTION) == READY_PLAIN
    assert plain_text("A &lt; B") == "A &lt; B"
    assert plain_text("Fish &amp; <b>chips</b>") == "Fish & chips"
    assert plain_text(None) is None


def test_ready_for_pickup_status_code() -> None:
    """The derived code replaces `transit`, the raw value stays available."""
    now = dt_util.utcnow()
    data = ready_payload()
    assert derive_status_code(data, now) == STATUS_CODE_READY_FOR_PICKUP

    data["status"] = on_the_way_status()
    assert derive_status_code(data, now) == STATUS_CODE_TRANSIT


# --- integration ----------------------------------------------------------------


async def test_waiting_parcel_is_not_treated_as_overdue(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A parcel in a Packstation is polled rarely, not on the fast lane."""
    shipment_responses[TRACKING_NUMBER] = ready_payload()
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    coordinator = entry.runtime_data.coordinator
    state = coordinator.states[TRACKING_NUMBER]
    assert state.delivery_imminent(dt_util.utcnow()) is True
    assert state.priority(dt_util.utcnow()) is ShipmentPriority.AWAITING_PICKUP
    assert coordinator.effective_interval(state) == coordinator.priority_floor(
        ShipmentPriority.AWAITING_PICKUP
    )


async def test_sensors_show_pickup_location_and_plain_text(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The status sensors carry no HTML and the Packstation gets a sensor."""
    shipment_responses[TRACKING_NUMBER] = ready_payload()
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    prefix = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
    status_code = hass.states.get(f"{prefix}_status_code")
    assert status_code.state == STATUS_CODE_READY_FOR_PICKUP
    assert status_code.attributes["status_code_api"] == "transit"
    assert status_code.attributes["description"] == READY_PLAIN
    assert status_code.attributes["status_remark"] == READY_PLAIN

    description = hass.states.get(f"{prefix}_status_description")
    assert description.state == READY_PLAIN

    location = hass.states.get(f"{prefix}_pickup_location")
    assert location.state == (
        "Packstation 205, Christian-Hülsmeyer-Str. 3, 27472 Cuxhaven"
    )
    assert location.attributes["locker_id"] == "205"
    assert location.attributes["postal_code"] == "27472"

    history = hass.states.get(f"{prefix}_status").attributes["events"]
    assert history[0]["description"] == READY_PLAIN


async def test_pickup_location_is_empty_for_home_delivery(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """An ordinary parcel has no pickup location."""
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    location = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_pickup_location")
    assert location.state == "unknown"


async def test_scan_into_packstation_fires_ready_for_pickup(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The scan entity reports the Packstation scan as `ready_for_pickup`."""
    on_the_way = shipment_payload(TRACKING_NUMBER)
    on_the_way["status"] = on_the_way_status()
    on_the_way["events"] = [on_the_way_status()]
    shipment_responses[TRACKING_NUMBER] = on_the_way
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    scans = async_capture_events(hass, EVENT_SCAN_ADDED)
    shipment_responses[TRACKING_NUMBER] = ready_payload()
    coordinator = entry.runtime_data.coordinator
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(scans) == 1
    assert scans[0].data["ready_for_pickup"] is True
    assert scans[0].data["description"] == READY_PLAIN

    event = hass.states.get(f"event.dhl_{TRACKING_NUMBER.lower()}_tracking_scan")
    assert event.attributes["event_type"] == "ready_for_pickup"
    status_event = hass.states.get(
        f"event.dhl_{TRACKING_NUMBER.lower()}_shipment_status"
    )
    assert status_event.attributes["event_type"] == "ready_for_pickup"
