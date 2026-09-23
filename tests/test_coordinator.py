"""Rate limiting, backoff, scheduling and event tests."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.dhl_tracking.api import (
    DhlAuthError,
    DhlConnectionError,
    DhlNotFoundError,
    DhlRateLimitError,
)
from custom_components.dhl_tracking.const import (
    DAILY_REQUEST_BUDGET,
    DELIVERED_SCAN_INTERVAL,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    MIN_SCAN_INTERVAL,
    RATE_LIMIT_BACKOFF_MAX,
    RATE_LIMIT_BACKOFF_START,
    SERVICE_ADD_SHIPMENT,
)
from custom_components.dhl_tracking.coordinator import RequestBudget
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import OTHER_TRACKING_NUMBER, TRACKING_NUMBER, shipment_payload

# Tolerance for the floating point fair-share arithmetic.
EPSILON = 1e-6


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int
) -> None:
    """Move time forward and let scheduled coordinator work run."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_one_request_per_shipment_per_poll(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The API has no batch endpoint, so each shipment costs one request."""
    entry = build_config_entry(
        shipments=[
            {"tracking_number": TRACKING_NUMBER},
            {"tracking_number": OTHER_TRACKING_NUMBER},
        ],
        options={"scan_interval": MIN_SCAN_INTERVAL},
    )
    await setup_integration(hass, entry)

    assert mock_api.call_count == 2
    assert entry.runtime_data.coordinator.budget.count == 2


async def test_fair_share_interval_respects_daily_budget(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """With many shipments the effective interval is stretched automatically."""
    entry = build_config_entry(
        shipments=[{"tracking_number": f"0034043400000000{i:04d}"} for i in range(40)],
        options={"scan_interval": MIN_SCAN_INTERVAL},
    )
    await setup_integration(hass, entry)
    coordinator = entry.runtime_data.coordinator

    # 40 active shipments, budget 200 -> 5 calls per shipment per day.
    assert coordinator.active_count() == 40
    assert coordinator.fair_share_interval() == timedelta(seconds=86400 / 5)
    # The configured 5 minute interval is overruled by the budget.
    state = next(iter(coordinator.states.values()))
    assert coordinator.effective_interval(state) == timedelta(seconds=86400 / 5)
    assert coordinator.estimated_daily_requests() == pytest.approx(DAILY_REQUEST_BUDGET)


async def test_configured_interval_wins_for_few_shipments(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A single shipment is polled at the configured interval."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    state = coordinator.states[TRACKING_NUMBER]
    assert coordinator.effective_interval(state) == timedelta(
        seconds=coordinator.options.scan_interval
    )
    assert coordinator.estimated_daily_requests() == pytest.approx(
        86400 / coordinator.options.scan_interval
    )


async def test_delivered_shipments_are_polled_once_a_day(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A delivered shipment drops to the slow schedule."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    coordinator = entry.runtime_data.coordinator
    state = coordinator.states[TRACKING_NUMBER]
    assert state.delivered
    assert coordinator.effective_interval(state) == timedelta(
        seconds=DELIVERED_SCAN_INTERVAL
    )
    assert coordinator.estimated_daily_requests() == pytest.approx(1.0)


async def test_delivered_shipments_can_be_ignored_completely(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """With poll_delivered disabled a delivered shipment is never polled again."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    entry = build_config_entry(
        shipments=[{"tracking_number": TRACKING_NUMBER}],
        options={"poll_delivered": False},
    )
    await setup_integration(hass, entry)

    coordinator = entry.runtime_data.coordinator
    assert coordinator.effective_interval(coordinator.states[TRACKING_NUMBER]) is None
    assert coordinator.estimated_daily_requests() == 0.0


async def test_daily_budget_is_enforced(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """When the budget is exhausted no further request is made."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    calls_before = mock_api.call_count
    coordinator.budget.count = DAILY_REQUEST_BUDGET
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()

    assert mock_api.call_count == calls_before
    assert coordinator.budget.remaining == 0


async def test_budget_resets_on_a_new_day(hass: HomeAssistant) -> None:
    """The counter rolls over at local midnight."""
    budget = RequestBudget(daily_budget=10)
    now = dt_util.utcnow()
    budget.roll_over(now)
    budget.consume()
    budget.consume()
    assert budget.count == 2

    budget.roll_over(now + timedelta(days=1))
    assert budget.count == 0
    assert budget.remaining == 10


async def test_http_429_triggers_exponential_backoff(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A 429 pauses the coordinator and the pause grows on repeated hits."""
    shipment_responses[TRACKING_NUMBER] = DhlRateLimitError()
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    coordinator = entry.runtime_data.coordinator
    budget = coordinator.budget
    assert budget.backoff_until is not None
    first_backoff = budget.backoff_until - dt_util.utcnow()
    assert first_backoff <= timedelta(seconds=RATE_LIMIT_BACKOFF_START)

    # While the backoff is active no request is made at all.
    calls = mock_api.call_count
    await coordinator.async_refresh()
    assert mock_api.call_count == calls

    # A second 429 doubles the backoff.
    budget.backoff_until = None
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    second_backoff = budget.backoff_until - dt_util.utcnow()
    assert second_backoff > first_backoff
    assert second_backoff <= timedelta(seconds=RATE_LIMIT_BACKOFF_MAX)


async def test_backoff_uses_retry_after(hass: HomeAssistant) -> None:
    """Retry-After never shortens the backoff below our own minimum."""
    budget = RequestBudget()
    now = dt_util.utcnow()

    budget.note_rate_limited(now, 30)
    assert budget.backoff_until == now + timedelta(seconds=RATE_LIMIT_BACKOFF_START)

    budget.note_success()
    budget.note_rate_limited(now, 99999999)
    assert budget.backoff_until == now + timedelta(seconds=RATE_LIMIT_BACKOFF_MAX)


async def test_no_aggressive_retry_after_not_found(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A 404 marks the shipment unavailable, it does not retry immediately."""
    shipment_responses[TRACKING_NUMBER] = DhlNotFoundError(TRACKING_NUMBER)
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    coordinator = entry.runtime_data.coordinator
    assert coordinator.states[TRACKING_NUMBER].error == "not_found"
    assert coordinator.last_update_success is True

    calls = mock_api.call_count
    await coordinator.async_refresh()
    # Not due yet, so no extra request.
    assert mock_api.call_count == calls

    # The entity exists but reports "unavailable" instead of a stale value.
    state = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_status")
    assert state is not None
    assert state.state == "unavailable"


async def test_connection_error_keeps_previous_data(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A transient API error does not wipe the last known payload."""
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)
    coordinator = entry.runtime_data.coordinator
    assert coordinator.states[TRACKING_NUMBER].data is not None

    shipment_responses[TRACKING_NUMBER] = DhlConnectionError()
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()

    assert coordinator.states[TRACKING_NUMBER].error == "api_error"
    assert coordinator.states[TRACKING_NUMBER].data is not None


async def test_auth_error_starts_reauth(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """An invalid API key puts the entry into the reauth flow."""
    shipment_responses[TRACKING_NUMBER] = DhlAuthError()
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    assert entry.state is ConfigEntryState.LOADED


async def test_status_change_event(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A changed status fires dhl_tracking_status_changed."""
    entry = build_config_entry(
        shipments=[{"tracking_number": TRACKING_NUMBER, "name": "Testpaket"}]
    )
    await setup_integration(hass, entry)
    coordinator = entry.runtime_data.coordinator

    events = async_capture_events(hass, EVENT_STATUS_CHANGED)

    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()

    assert len(events) == 1
    assert events[0].data == {
        "tracking_number": TRACKING_NUMBER,
        "name": "Testpaket",
        "old_status": "In transit",
        "new_status": "Delivered",
        "old_status_code": "transit",
        "new_status_code": "delivered",
    }

    # An unchanged status does not fire another event.
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    assert len(events) == 1


async def test_no_status_event_on_restart(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The first payload after a restart is not reported as a change."""
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await setup_integration(hass, mock_config_entry)
    assert events == []


async def test_status_event_for_newly_added_shipment(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """A shipment added at runtime reports its first status."""
    entry = build_config_entry(shipments=[])
    await setup_integration(hass, entry)
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {"tracking_number": TRACKING_NUMBER},
        blocking=True,
    )
    await entry.runtime_data.coordinator.async_refresh()

    assert len(events) == 1
    assert events[0].data["old_status"] is None
    assert events[0].data["new_status"] == "In transit"


async def test_events_contain_no_personal_data(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Event payloads are limited to the tracking number and display name."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)

    coordinator.states[TRACKING_NUMBER].status = "Something else"
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()

    assert len(events) == 1
    assert set(events[0].data) == {
        "tracking_number",
        "name",
        "old_status",
        "new_status",
        "old_status_code",
        "new_status_code",
    }
    payload = str(events[0].data)
    assert "Erika Mustermann" not in payload
    assert "40667" not in payload


async def test_state_survives_restart_without_extra_request(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Cached payloads and poll timestamps are restored from the store."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    assert mock_api.call_count == 1
    await coordinator.store.async_save_now()

    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    restored = mock_config_entry.runtime_data.coordinator
    assert restored.states[TRACKING_NUMBER].data is not None
    assert restored.states[TRACKING_NUMBER].last_polled is not None
    assert restored.budget.count == 1
    # The shipment is not due yet, so the restart did not cost a request.
    assert mock_api.call_count == 1


@pytest.mark.parametrize(
    ("active", "fair_share_minutes", "effective_minutes", "requests_per_day"),
    [
        (1, 7.2, 30, 48),
        (2, 14.4, 30, 96),
        (4, 28.8, 30, 192),
        (5, 36, 36, 200),
        (10, 72, 72, 200),
        (20, 144, 144, 200),
    ],
)
async def test_documented_rate_limit_table(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    active: int,
    fair_share_minutes: float,
    effective_minutes: float,
    requests_per_day: int,
) -> None:
    """Verify the rate limit table documented in the README."""
    entry = build_config_entry(
        shipments=[
            {"tracking_number": f"0034043400000000{i:04d}"} for i in range(active)
        ]
    )
    await setup_integration(hass, entry)
    coordinator = entry.runtime_data.coordinator

    assert coordinator.active_count() == active
    assert coordinator.fair_share_interval().total_seconds() / 60 == pytest.approx(
        fair_share_minutes
    )
    state = next(iter(coordinator.states.values()))
    assert coordinator.effective_interval(state).total_seconds() / 60 == pytest.approx(
        effective_minutes
    )
    assert coordinator.estimated_daily_requests() == pytest.approx(requests_per_day)
    # EPSILON absorbs the float division in the fair share calculation; the
    # hard counter in RequestBudget enforces the integer budget exactly.
    assert coordinator.estimated_daily_requests() <= DAILY_REQUEST_BUDGET + EPSILON


async def test_daily_requests_never_exceed_the_budget(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """Whatever the shipment count, the estimated usage stays in budget."""
    for count in (1, 3, 7, 25, 60, 150):
        entry = build_config_entry(
            shipments=[
                {"tracking_number": f"0034043411000000{i:04d}"} for i in range(count)
            ],
            options={"scan_interval": MIN_SCAN_INTERVAL},
            unique_id=f"fingerprint-{count}",
        )
        await setup_integration(hass, entry)
        coordinator = entry.runtime_data.coordinator
        assert coordinator.estimated_daily_requests() <= DAILY_REQUEST_BUDGET + EPSILON
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
