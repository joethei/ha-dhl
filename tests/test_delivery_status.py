"""Tests for the derived out_for_delivery status and the delivery window."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.dhl_tracking.const import (
    STATUS_CODE_OUT_FOR_DELIVERY,
    STATUS_CODE_TRANSIT,
    STATUS_CODES,
)
from custom_components.dhl_tracking.coordinator import (
    ShipmentPriority,
    derive_status_code,
    is_out_for_delivery,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import TRACKING_NUMBER, shipment_payload


def window(start_hour: int, end_hour: int, *, day_offset: int = 0) -> dict[str, str]:
    """Return a delivery window in local time, without a UTC offset.

    This is how DHL actually sends it: ``2026-09-23T13:20:00``.
    """
    day = (dt_util.now() + timedelta(days=day_offset)).date()
    return {
        "estimatedFrom": f"{day.isoformat()}T{start_hour:02d}:00:00",
        "estimatedThrough": f"{day.isoformat()}T{end_hour:02d}:00:00",
    }


def multi_day_window() -> dict[str, str]:
    """Return the ordinary "somewhere this week" forecast."""
    start = dt_util.now().date()
    end = start + timedelta(days=2)
    return {
        "estimatedFrom": f"{start.isoformat()}T08:00:00",
        "estimatedThrough": f"{end.isoformat()}T18:00:00",
    }


def payload(**kwargs) -> dict:
    """Return a transit payload with the given forecast."""
    return shipment_payload(TRACKING_NUMBER, estimated_delivery=None, **kwargs)


# --- derivation ---------------------------------------------------------------


def test_out_for_delivery_enum_value_is_additive() -> None:
    """The new value is appended, the documented five stay untouched."""
    assert STATUS_CODES[:5] == (
        "delivered",
        "failure",
        "pre-transit",
        "transit",
        "unknown",
    )
    assert STATUS_CODES[5] == STATUS_CODE_OUT_FOR_DELIVERY


def test_same_day_window_means_out_for_delivery() -> None:
    """A narrow window opening and closing today qualifies."""
    now = dt_util.utcnow()
    local_now = dt_util.as_local(now)
    data = payload(
        delivery_time_frame=window(local_now.hour, min(23, local_now.hour + 2))
    )
    assert is_out_for_delivery(data, now) is True
    assert derive_status_code(data, now) == STATUS_CODE_OUT_FOR_DELIVERY


def test_multi_day_window_is_plain_transit() -> None:
    """The ordinary multi-day forecast must not be read as out for delivery."""
    now = dt_util.utcnow()
    data = payload(delivery_time_frame=multi_day_window())
    assert is_out_for_delivery(data, now) is False
    assert derive_status_code(data, now) == STATUS_CODE_TRANSIT


def test_window_on_another_day_is_plain_transit() -> None:
    """A narrow window for tomorrow is not out for delivery yet."""
    now = dt_util.utcnow()
    data = payload(delivery_time_frame=window(10, 12, day_offset=1))
    assert is_out_for_delivery(data, now) is False


def test_no_window_is_plain_transit() -> None:
    """Without a structured window nothing is derived."""
    now = dt_util.utcnow()
    assert is_out_for_delivery(payload(), now) is False
    assert derive_status_code(payload(), now) == STATUS_CODE_TRANSIT


def test_status_text_is_never_used_for_the_derivation() -> None:
    """DHL does not document what "PO" means, so it must not drive anything.

    DHL developer support states the status descriptions "completely depend on
    each division and their logic" and lists "Out for Delivery" as planned but
    unavailable, so matching them would be guesswork.
    """
    now = dt_util.utcnow()
    data = payload()
    data["status"]["status"] = "PO"
    data["status"]["description"] = (
        "Die Sendung wurde in das Zustellfahrzeug geladen. "
        "Die Zustellung erfolgt voraussichtlich heute."
    )
    assert derive_status_code(data, now) == STATUS_CODE_TRANSIT


def test_delivered_is_never_overridden() -> None:
    """A delivered shipment stays delivered even inside a window."""
    now = dt_util.utcnow()
    data = shipment_payload(
        TRACKING_NUMBER,
        status_code="delivered",
        estimated_delivery=None,
        delivery_time_frame=window(0, 23),
    )
    assert derive_status_code(data, now) == "delivered"


def test_undocumented_api_code_is_clamped() -> None:
    """A value outside the documented enum still reports unknown."""
    now = dt_util.utcnow()
    data = payload()
    data["status"]["statusCode"] = "teleported"
    assert derive_status_code(data, now) == "unknown"


def test_missing_status_yields_none() -> None:
    """No status block, no derived code."""
    assert derive_status_code({}, dt_util.utcnow()) is None
    assert derive_status_code(None, dt_util.utcnow()) is None


# --- end to end ----------------------------------------------------------------


async def test_sensor_reports_out_for_delivery(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The status code sensor exposes the derived value and the raw one."""
    local_now = dt_util.now()
    shipment_responses[TRACKING_NUMBER] = payload(
        delivery_time_frame=window(local_now.hour, min(23, local_now.hour + 2))
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    state = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_status_code")
    assert state.state == STATUS_CODE_OUT_FOR_DELIVERY
    # The unmodified API value stays reachable.
    assert state.attributes["status_code_api"] == STATUS_CODE_TRANSIT
    assert STATUS_CODE_OUT_FOR_DELIVERY in state.attributes["options"]


async def test_out_for_delivery_gets_the_fast_lane(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A parcel on the vehicle is polled at the imminent priority."""
    local_now = dt_util.now()
    shipment_responses[TRACKING_NUMBER] = payload(
        delivery_time_frame=window(local_now.hour, min(23, local_now.hour + 2))
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    coordinator = entry.runtime_data.coordinator
    state = coordinator.states[TRACKING_NUMBER]
    assert state.priority(dt_util.utcnow()) is ShipmentPriority.IMMINENT


@pytest.mark.parametrize("raw_offset", ["", "+02:00"])
async def test_time_frame_attributes_are_timezone_aware(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    shipment_responses: dict,
    raw_offset: str,
) -> None:
    """The window is published with an offset, the raw value is kept too."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER,
        estimated_delivery=None,
        delivery_time_frame={
            "estimatedFrom": f"2026-09-23T13:20:00{raw_offset}",
            "estimatedThrough": f"2026-09-23T14:50:00{raw_offset}",
        },
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    attrs = hass.states.get(
        f"sensor.dhl_{TRACKING_NUMBER.lower()}_estimated_delivery"
    ).attributes

    for key in ("time_frame_from", "time_frame_through"):
        parsed = dt_util.parse_datetime(attrs[key])
        assert parsed is not None
        assert parsed.tzinfo is not None, f"{key} has no timezone"

    # Nothing is lost: the untouched API strings remain available.
    assert attrs["raw_time_frame_from"] == f"2026-09-23T13:20:00{raw_offset}"
    assert attrs["raw_time_frame_through"] == f"2026-09-23T14:50:00{raw_offset}"


async def test_time_frame_remark_attribute(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The human readable forecast is offered under both attribute names."""
    data = payload(delivery_time_frame=window(10, 12))
    data["estimatedTimeOfDeliveryRemark"] = "Zustellung heute zwischen 10 und 12 Uhr"
    shipment_responses[TRACKING_NUMBER] = data
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    attrs = hass.states.get(
        f"sensor.dhl_{TRACKING_NUMBER.lower()}_estimated_delivery"
    ).attributes
    assert attrs["time_frame_remark"] == "Zustellung heute zwischen 10 und 12 Uhr"
    assert attrs["remark"] == attrs["time_frame_remark"]


async def test_event_history_timestamps_are_timezone_aware(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The event history must not stay naive while the window is aware.

    DHL sends event timestamps without a UTC offset, just like the delivery
    window. A template comparing them against `now()` would otherwise fail on
    a naive/aware mismatch.
    """
    data = payload()
    data["events"] = [
        {
            "timestamp": "2026-09-23T08:24:00",
            "status": "PO",
            "statusCode": "transit",
            "statusDetailed": "SRTED_NRQRD_PO",
            "description": "Die Sendung wurde in das Zustellfahrzeug geladen.",
        }
    ]
    shipment_responses[TRACKING_NUMBER] = data
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    events = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_status").attributes[
        "events"
    ]
    parsed = dt_util.parse_datetime(events[0]["timestamp"])
    assert parsed is not None
    assert parsed.tzinfo is not None
    # The detailed code rides along, like at the top level.
    assert events[0]["status_detailed"] == "SRTED_NRQRD_PO"
