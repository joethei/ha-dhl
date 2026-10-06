"""Tests for the derived `delayed` status and expired delivery forecasts.

The developer API leaves a delivery window in place after it passed, so a
late parcel would keep showing a delivery time that is long gone.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.dhl_tracking.const import (
    EVENT_DELIVERY_OVERDUE,
    STATUS_CODE_DELAYED,
    STATUS_CODE_DELIVERED,
    STATUS_CODE_OUT_FOR_DELIVERY,
    STATUS_CODE_READY_FOR_PICKUP,
    STATUS_CODE_TRANSIT,
)
from custom_components.dhl_tracking.coordinator import derive_status_code, overdue_by
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import OTHER_TRACKING_NUMBER, TRACKING_NUMBER, shipment_payload
from .test_pickup import ready_status

PREFIX = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
NEXT = "sensor.dhl_tracking_next_delivery"


def window_ending(now: datetime, ago: timedelta) -> dict[str, str]:
    """Return a one hour delivery window that closed `ago` before `now`."""
    end = now - ago
    return {
        "estimatedFrom": (end - timedelta(hours=1)).isoformat(),
        "estimatedThrough": end.isoformat(),
    }


def late_payload(
    now: datetime, ago: timedelta, number: str = TRACKING_NUMBER, **kwargs
) -> dict:
    """Return a payload whose delivery window closed `ago` before `now`."""
    return shipment_payload(
        number,
        estimated_delivery=None,
        delivery_time_frame=window_ending(now, ago),
        **kwargs,
    )


# --- derivation ---------------------------------------------------------------


def test_delayed_after_the_grace_period() -> None:
    """Two hours after the window closed the parcel counts as delayed."""
    now = dt_util.utcnow()
    data = late_payload(now, timedelta(hours=3))
    assert derive_status_code(data, now) == STATUS_CODE_DELAYED
    assert overdue_by(data, now) == timedelta(hours=3)


def test_not_delayed_inside_the_grace_period() -> None:
    """Shortly after the window the courier may just be running late."""
    now = dt_util.utcnow()
    data = late_payload(now, timedelta(hours=1))
    assert derive_status_code(data, now) in {
        STATUS_CODE_TRANSIT,
        STATUS_CODE_OUT_FOR_DELIVERY,
    }
    assert overdue_by(data, now) == timedelta(hours=1)


def test_future_forecast_is_not_overdue() -> None:
    """A forecast still ahead is neither expired nor delayed."""
    now = dt_util.utcnow()
    data = late_payload(now, timedelta(days=-2))
    assert overdue_by(data, now) is None
    assert derive_status_code(data, now) == STATUS_CODE_TRANSIT


def test_day_only_forecast_is_late_once_the_day_is_over() -> None:
    """ "Some time on Tuesday" is not late before Tuesday ends."""
    now = dt_util.utcnow()
    today = dt_util.as_local(now).date()
    data = shipment_payload(TRACKING_NUMBER, estimated_delivery=today.isoformat())
    assert overdue_by(data, now) is None

    yesterday = (today - timedelta(days=1)).isoformat()
    data = shipment_payload(TRACKING_NUMBER, estimated_delivery=yesterday)
    assert overdue_by(data, now) is not None


def test_delivered_and_waiting_parcels_are_never_delayed() -> None:
    """An old forecast says nothing once the parcel arrived or waits."""
    now = dt_util.utcnow()
    delivered = late_payload(now, timedelta(hours=5), status_code="delivered")
    assert overdue_by(delivered, now) is None
    assert derive_status_code(delivered, now) == STATUS_CODE_DELIVERED

    waiting = late_payload(now, timedelta(hours=5))
    waiting["status"] = ready_status()
    assert overdue_by(waiting, now) is None
    assert derive_status_code(waiting, now) == STATUS_CODE_READY_FOR_PICKUP


# --- sensors ----------------------------------------------------------------------


async def test_delivery_sensors_flag_an_expired_forecast(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """DHL's time stays visible, marked as expired with the delay."""
    shipment_responses[TRACKING_NUMBER] = late_payload(
        dt_util.utcnow(), timedelta(hours=3)
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    assert hass.states.get(f"{PREFIX}_status_code").state == STATUS_CODE_DELAYED
    for key in ("estimated_delivery", "delivery_day"):
        attrs = hass.states.get(f"{PREFIX}_{key}").attributes
        assert attrs["forecast_expired"] is True
        assert 179 <= attrs["overdue_minutes"] <= 181


async def test_delivery_sensors_without_expired_forecast(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """A forecast ahead carries `forecast_expired: false` and no delay."""
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    attrs = hass.states.get(f"{PREFIX}_estimated_delivery").attributes
    assert attrs["forecast_expired"] is False
    assert "overdue_minutes" not in attrs


async def test_next_delivery_skips_expired_forecasts(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A late parcel no longer pins the sensor to a past time."""
    now = dt_util.utcnow()
    shipment_responses[TRACKING_NUMBER] = late_payload(now, timedelta(hours=3))
    shipment_responses[OTHER_TRACKING_NUMBER] = late_payload(
        now, timedelta(hours=-5), OTHER_TRACKING_NUMBER
    )
    entry = build_config_entry(
        shipments=[
            {"tracking_number": TRACKING_NUMBER, "name": "Spaet"},
            {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Morgen"},
        ]
    )
    await setup_integration(hass, entry)

    state = hass.states.get(NEXT)
    assert state.attributes["tracking_number"] == OTHER_TRACKING_NUMBER
    assert dt_util.parse_datetime(state.state) > now
    [late] = state.attributes["delayed_shipments"]
    assert late["tracking_number"] == TRACKING_NUMBER
    assert late["name"] == "Spaet"
    assert 179 <= late["overdue_minutes"] <= 181


async def test_waiting_parcel_fires_no_overdue_event(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A parcel in a Packstation is not an overdue delivery."""
    data = late_payload(dt_util.utcnow(), timedelta(hours=5))
    data["status"] = ready_status()
    shipment_responses[TRACKING_NUMBER] = data
    overdue = async_capture_events(hass, EVENT_DELIVERY_OVERDUE)
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    coordinator = entry.runtime_data.coordinator
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert overdue == []
