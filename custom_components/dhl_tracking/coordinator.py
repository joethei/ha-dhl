"""Data update coordinator for the DHL Tracking integration.

Scheduling strategy
-------------------
The free DHL developer plan for the "Shipment Tracking - Unified" API allows
250 calls per day and at most one call every five seconds, and the API has no
batch endpoint: ``GET /shipments`` accepts exactly one ``trackingNumber``.
Every shipment therefore costs one request per poll.

To stay inside that quota the coordinator does *not* poll every shipment on
every tick. On each tick it collects the shipments that are due, where the
per-shipment interval is::

    delivered shipment: DELIVERED_SCAN_INTERVAL (24 h), or never when the
                        "poll delivered shipments" option is disabled
    active shipment:    max(configured scan interval, fair share interval)

    fair share interval = 86400 / (active_budget / active_count)  [seconds]
    active_budget       = max(active_count, DAILY_REQUEST_BUDGET - delivered_count)

``DAILY_REQUEST_BUDGET`` (200) stays below the documented limit of 250 so that
credential checks and manual refreshes cannot exhaust the quota. A hard
counter enforces the budget as a second line of defence, and an HTTP 429
response puts the whole coordinator into exponential backoff.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    DhlApiError,
    DhlAuthError,
    DhlNotFoundError,
    DhlRateLimitError,
    DhlTrackingApi,
)
from .const import (
    API_MIN_SECONDS_BETWEEN_CALLS,
    DAILY_REQUEST_BUDGET,
    DELIVERED_SCAN_INTERVAL,
    DELIVERY_IMMINENT_LEAD_HOURS,
    DELIVERY_OVERDUE_GRACE_HOURS,
    DOMAIN,
    EVENT_SHIPMENT_ADDED,
    EVENT_SHIPMENT_REMOVED,
    EVENT_STATUS_CHANGED,
    IMMINENT_INTERVAL_DIVISOR,
    MIN_SCAN_INTERVAL,
    PRE_TRANSIT_INTERVAL_FACTOR,
    PRIORITY_WEIGHT_IMMINENT,
    PRIORITY_WEIGHT_PRE_TRANSIT,
    PRIORITY_WEIGHT_TRANSIT,
    RATE_LIMIT_BACKOFF_MAX,
    RATE_LIMIT_BACKOFF_START,
    STATUS_CODE_DELIVERED,
    STATUS_CODE_PRE_TRANSIT,
)
from .models import DhlOptions, Shipment
from .store import DhlStateStore

_LOGGER = logging.getLogger(__name__)

SECONDS_PER_DAY = 86400


class ShipmentPriority(StrEnum):
    """How urgently a shipment needs fresh data."""

    IMMINENT = "imminent"
    """Delivery is forecast for right now, or was forecast and has not
    happened yet - this is as close to "out for delivery" as the official API
    allows us to get."""

    TRANSIT = "transit"
    """On its way, but no imminent delivery forecast."""

    PRE_TRANSIT = "pre_transit"
    """Announced by the sender, not picked up yet. Changes rarely."""

    DELIVERED = "delivered"
    """Done. Polled once a day at most, or not at all."""


PRIORITY_WEIGHTS: dict[ShipmentPriority, int] = {
    ShipmentPriority.IMMINENT: PRIORITY_WEIGHT_IMMINENT,
    ShipmentPriority.TRANSIT: PRIORITY_WEIGHT_TRANSIT,
    ShipmentPriority.PRE_TRANSIT: PRIORITY_WEIGHT_PRE_TRANSIT,
}

# Order used when the request budget is not enough for everything that is due.
PRIORITY_ORDER: dict[ShipmentPriority, int] = {
    ShipmentPriority.IMMINENT: 0,
    ShipmentPriority.TRANSIT: 1,
    ShipmentPriority.PRE_TRANSIT: 2,
    ShipmentPriority.DELIVERED: 3,
}


@dataclass(slots=True)
class ShipmentState:
    """Runtime state of a single tracked shipment."""

    shipment: Shipment
    data: dict[str, Any] | None = None
    last_polled: datetime | None = None
    last_success: datetime | None = None
    error: str | None = None
    status: str | None = None
    status_code: str | None = None

    @property
    def tracking_number(self) -> str:
        """Return the tracking number."""
        return self.shipment.tracking_number

    @property
    def delivered(self) -> bool:
        """Return whether the shipment has been delivered."""
        return self.status_code == STATUS_CODE_DELIVERED

    @property
    def available(self) -> bool:
        """Return whether entities for this shipment should report data."""
        return self.data is not None

    @property
    def delivered_at(self) -> datetime | None:
        """Return the delivery timestamp, when the shipment was delivered."""
        if not self.delivered or not self.data:
            return None
        return parse_api_datetime((self.data.get("status") or {}).get("timestamp"))

    def priority(self, now: datetime) -> ShipmentPriority:
        """Return how urgently this shipment needs fresh data."""
        if self.delivered:
            return ShipmentPriority.DELIVERED
        if self.delivery_imminent(now):
            return ShipmentPriority.IMMINENT
        if self.status_code == STATUS_CODE_PRE_TRANSIT:
            return ShipmentPriority.PRE_TRANSIT
        return ShipmentPriority.TRANSIT

    def delivery_imminent(self, now: datetime) -> bool:
        """Return whether DHL forecasts the delivery for right about now.

        Uses only the structured forecast fields of the official API. The
        textual status fields are localized free text and deliberately not
        matched against.
        """
        if not self.data:
            return False

        lead = timedelta(hours=DELIVERY_IMMINENT_LEAD_HOURS)
        grace = timedelta(hours=DELIVERY_OVERDUE_GRACE_HOURS)

        frame = self.data.get("estimatedDeliveryTimeFrame") or {}
        start = parse_api_datetime(frame.get("estimatedFrom"))
        end = parse_api_datetime(frame.get("estimatedThrough"))
        # Inside the delivery window, close enough to its start, or overdue.
        if (
            end is not None
            and now <= end + grace
            and (start is None or now >= start - lead)
        ):
            return True

        eta = parse_api_datetime(self.data.get("estimatedTimeOfDelivery"))
        return eta is not None and eta - lead <= now <= eta + grace


@dataclass(slots=True)
class ShipmentDiff:
    """Result of applying a new shipment list."""

    added: list[Shipment] = field(default_factory=list)
    removed: list[Shipment] = field(default_factory=list)
    updated: list[Shipment] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Return whether anything changed."""
        return bool(self.added or self.removed or self.updated)


ShipmentListener = Callable[[ShipmentDiff], Coroutine[Any, Any, None]]


def parse_api_datetime(value: Any) -> datetime | None:
    """Parse a DHL API date-time value into an aware ``datetime``.

    The API documents ``format: date-time`` but some business units omit the
    UTC offset. Naive values are interpreted in the Home Assistant time zone.
    """
    if not isinstance(value, str) or not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        parsed_date = dt_util.parse_date(value)
        if parsed_date is None:
            return None
        parsed = datetime.combine(parsed_date, datetime.min.time())
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed


class RequestBudget:
    """Tracks the daily DHL request budget and the 429 backoff."""

    def __init__(self, daily_budget: int = DAILY_REQUEST_BUDGET) -> None:
        """Initialize the budget."""
        self.daily_budget = daily_budget
        self.day: str | None = None
        self.count = 0
        self.backoff_until: datetime | None = None
        self._backoff_seconds = 0

    def as_dict(self) -> dict[str, Any]:
        """Return the persisted representation."""
        return {
            "day": self.day,
            "count": self.count,
            "backoff_until": (
                self.backoff_until.isoformat() if self.backoff_until else None
            ),
            "backoff_seconds": self._backoff_seconds,
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore a previously persisted budget."""
        self.day = data.get("day")
        self.count = int(data.get("count") or 0)
        self.backoff_until = parse_api_datetime(data.get("backoff_until"))
        self._backoff_seconds = int(data.get("backoff_seconds") or 0)

    def roll_over(self, now: datetime) -> None:
        """Reset the counter when a new local day started."""
        today = dt_util.as_local(now).date().isoformat()
        if self.day != today:
            if self.day is not None:
                _LOGGER.debug(
                    "New day (%s): resetting DHL request counter from %s",
                    today,
                    self.count,
                )
            self.day = today
            self.count = 0

    @property
    def remaining(self) -> int:
        """Return how many requests are still allowed today."""
        return max(0, self.daily_budget - self.count)

    def has_capacity(self) -> bool:
        """Return whether another request may be spent today."""
        return self.remaining > 0

    def consume(self) -> None:
        """Account for one spent request."""
        self.count += 1

    def note_success(self) -> None:
        """Clear the backoff after a successful request."""
        self.backoff_until = None
        self._backoff_seconds = 0

    def note_rate_limited(self, now: datetime, retry_after: int | None) -> None:
        """Apply exponential backoff after an HTTP 429 response."""
        if retry_after:
            seconds = min(
                max(retry_after, RATE_LIMIT_BACKOFF_START), RATE_LIMIT_BACKOFF_MAX
            )
        elif self._backoff_seconds:
            seconds = min(self._backoff_seconds * 2, RATE_LIMIT_BACKOFF_MAX)
        else:
            seconds = RATE_LIMIT_BACKOFF_START
        self._backoff_seconds = seconds
        self.backoff_until = now + timedelta(seconds=seconds)

    def is_blocked(self, now: datetime) -> bool:
        """Return whether the backoff is still active."""
        return self.backoff_until is not None and now < self.backoff_until


class DhlUpdateCoordinator(DataUpdateCoordinator[dict[str, ShipmentState]]):
    """Fetch DHL tracking data for all shipments of one config entry."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: DhlTrackingApi,
        options: DhlOptions,
        store: DhlStateStore,
    ) -> None:
        """Initialize the coordinator."""
        self.api = api
        self.options = options
        self.store = store
        self.budget = RequestBudget()
        self.states: dict[str, ShipmentState] = {}
        self.min_seconds_between_calls = API_MIN_SECONDS_BETWEEN_CALLS

        self._shipment_listeners: list[ShipmentListener] = []
        self._last_request_at: datetime | None = None
        self._announce_first_status: set[str] = set()

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=options.scan_interval),
        )

    # -- lifecycle ----------------------------------------------------------

    async def async_initialize(self) -> None:
        """Restore persisted state and build the shipment states."""
        stored = await self.store.async_load()
        self.budget.restore(stored.get("budget") or {})
        stored_shipments: dict[str, Any] = stored.get("shipments") or {}

        for shipment in self.options.shipments:
            state = ShipmentState(shipment=shipment)
            if restored := stored_shipments.get(shipment.tracking_number):
                state.data = restored.get("data")
                state.last_polled = parse_api_datetime(restored.get("last_polled"))
                state.last_success = parse_api_datetime(restored.get("last_success"))
                state.status = restored.get("status")
                state.status_code = restored.get("status_code")
            self.states[shipment.tracking_number] = state

        self.data = self.states

    @callback
    def async_add_shipment_listener(
        self, listener: ShipmentListener
    ) -> Callable[[], None]:
        """Register a listener that is awaited whenever shipments change."""
        self._shipment_listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._shipment_listeners:
                self._shipment_listeners.remove(listener)

        return _remove

    def _persist(self) -> None:
        """Schedule a debounced save of the runtime state."""
        self.store.async_set(
            {
                "budget": self.budget.as_dict(),
                "shipments": {
                    tracking_number: {
                        "data": state.data,
                        "last_polled": (
                            state.last_polled.isoformat() if state.last_polled else None
                        ),
                        "last_success": (
                            state.last_success.isoformat()
                            if state.last_success
                            else None
                        ),
                        "status": state.status,
                        "status_code": state.status_code,
                    }
                    for tracking_number, state in self.states.items()
                },
            }
        )

    # -- shipment management -------------------------------------------------

    async def async_apply_options(self, options: DhlOptions) -> ShipmentDiff:
        """Apply new options, adding/removing shipments without a reload."""
        previous = self.options
        self.options = options

        if options.scan_interval != previous.scan_interval:
            self.update_interval = timedelta(seconds=options.scan_interval)

        diff = self._diff_shipments(options.shipments)
        if not diff:
            return diff

        for shipment in diff.removed:
            self.states.pop(shipment.tracking_number, None)
            self._announce_first_status.discard(shipment.tracking_number)
        for shipment in diff.added:
            self.states[shipment.tracking_number] = ShipmentState(shipment=shipment)
            self._announce_first_status.add(shipment.tracking_number)
        for shipment in diff.updated:
            self.states[shipment.tracking_number].shipment = shipment

        # Keep the stored order in sync with the option order.
        self.states = {
            shipment.tracking_number: self.states[shipment.tracking_number]
            for shipment in options.shipments
        }
        self.data = self.states

        for listener in list(self._shipment_listeners):
            await listener(diff)

        self._async_sync_devices(diff)
        self._persist()

        for shipment in diff.added:
            self.hass.bus.async_fire(
                EVENT_SHIPMENT_ADDED, _shipment_event_data(shipment)
            )
        for shipment in diff.removed:
            self.hass.bus.async_fire(
                EVENT_SHIPMENT_REMOVED, _shipment_event_data(shipment)
            )

        if diff.added:
            await self.async_request_refresh()

        return diff

    def _diff_shipments(self, shipments: Iterable[Shipment]) -> ShipmentDiff:
        """Compare the new shipment list against the current states."""
        diff = ShipmentDiff()
        new_by_number = {s.tracking_number: s for s in shipments}

        for tracking_number, shipment in new_by_number.items():
            if (state := self.states.get(tracking_number)) is None:
                diff.added.append(shipment)
            elif state.shipment != shipment:
                diff.updated.append(shipment)

        for tracking_number, state in self.states.items():
            if tracking_number not in new_by_number:
                diff.removed.append(state.shipment)

        return diff

    @callback
    def _async_sync_devices(self, diff: ShipmentDiff) -> None:
        """Remove devices of removed shipments and rename updated ones."""
        device_registry = dr.async_get(self.hass)

        for shipment in diff.removed:
            device = device_registry.async_get_device(
                identifiers={(DOMAIN, shipment.tracking_number)}
            )
            if device is not None:
                device_registry.async_remove_device(device.id)

        for shipment in diff.updated:
            device = device_registry.async_get_device(
                identifiers={(DOMAIN, shipment.tracking_number)}
            )
            if device is not None and device.name != shipment.display_name:
                device_registry.async_update_device(
                    device.id, name=shipment.display_name
                )

    # -- polling -------------------------------------------------------------

    def priority_counts(self, now: datetime | None = None) -> dict[str, int]:
        """Return the number of shipments per priority."""
        now = now or dt_util.utcnow()
        counts = dict.fromkeys(ShipmentPriority, 0)
        for state in self.states.values():
            counts[state.priority(now)] += 1
        return {priority.value: count for priority, count in counts.items()}

    def active_count(self, now: datetime | None = None) -> int:
        """Return the number of shipments that are not delivered yet."""
        return sum(1 for state in self.states.values() if not state.delivered)

    def delivered_count(self) -> int:
        """Return the number of delivered shipments."""
        return sum(1 for state in self.states.values() if state.delivered)

    def _total_weight(self, now: datetime) -> int:
        """Return the summed priority weight of all shipments still moving."""
        return sum(
            PRIORITY_WEIGHTS[state.priority(now)]
            for state in self.states.values()
            if not state.delivered
        )

    def _active_budget(self, now: datetime) -> int:
        """Return the daily requests available for shipments still moving.

        Delivered shipments are billed first at one call per day; whatever is
        left goes to the shipments that are still moving. The result is never
        below one, so a single active shipment is always polled.
        """
        delivered_calls = self.delivered_count() if self.options.poll_delivered else 0
        return max(1, self.budget.daily_budget - delivered_calls)

    def fair_share_interval(
        self,
        priority: ShipmentPriority = ShipmentPriority.TRANSIT,
        now: datetime | None = None,
    ) -> timedelta:
        """Return the budget derived interval for one priority.

        The daily budget is split across the shipments still moving in
        proportion to their priority weight::

            calls per day = active_budget * weight / total_weight

        With a single priority in play this reduces to an even split, so the
        behaviour is unchanged when nothing is forecast for delivery.
        """
        now = now or dt_util.utcnow()
        total_weight = self._total_weight(now)
        if total_weight == 0:
            return timedelta(seconds=DELIVERED_SCAN_INTERVAL)
        weight = PRIORITY_WEIGHTS[priority]
        calls_per_day = self._active_budget(now) * weight / total_weight
        return timedelta(seconds=SECONDS_PER_DAY / calls_per_day)

    def priority_floor(self, priority: ShipmentPriority) -> timedelta:
        """Return the shortest interval allowed for a priority."""
        scan_interval = self.options.scan_interval
        if priority is ShipmentPriority.IMMINENT:
            seconds = max(MIN_SCAN_INTERVAL, scan_interval // IMMINENT_INTERVAL_DIVISOR)
        elif priority is ShipmentPriority.PRE_TRANSIT:
            seconds = scan_interval * PRE_TRANSIT_INTERVAL_FACTOR
        else:
            seconds = scan_interval
        return timedelta(seconds=seconds)

    def effective_interval(
        self, state: ShipmentState, now: datetime | None = None
    ) -> timedelta | None:
        """Return the poll interval for a shipment, or ``None`` to never poll."""
        now = now or dt_util.utcnow()
        priority = state.priority(now)
        if priority is ShipmentPriority.DELIVERED:
            if not self.options.poll_delivered:
                return None
            return timedelta(seconds=DELIVERED_SCAN_INTERVAL)
        return max(
            self.priority_floor(priority),
            self.fair_share_interval(priority, now),
        )

    def estimated_daily_requests(self, now: datetime | None = None) -> float:
        """Return the scheduled number of API requests per day.

        This is the demand of the current schedule. It stays within the daily
        budget for any realistic number of shipments; should it ever exceed it
        (more tracked shipments than the budget has calls), the hard counter in
        :class:`RequestBudget` rations the requests and the priority order
        decides who is served first.
        """
        now = now or dt_util.utcnow()
        total = 0.0
        for state in self.states.values():
            if (interval := self.effective_interval(state, now)) is None:
                continue
            total += SECONDS_PER_DAY / interval.total_seconds()
        return total

    def _due_shipments(self, now: datetime) -> list[ShipmentState]:
        """Return the shipments that should be polled now, highest priority first."""
        due: list[ShipmentState] = []
        for state in self.states.values():
            interval = self.effective_interval(state, now)
            if interval is None:
                continue
            if state.last_polled is None or now - state.last_polled >= interval:
                due.append(state)

        # Imminent deliveries first, delivered shipments last; within one
        # priority the least recently polled shipment wins.
        due.sort(
            key=lambda s: (
                PRIORITY_ORDER[s.priority(now)],
                s.last_polled or datetime.min.replace(tzinfo=dt_util.UTC),
            )
        )
        return due

    async def _async_update_data(self) -> dict[str, ShipmentState]:
        """Poll the shipments that are due, respecting the request budget."""
        now = dt_util.utcnow()
        self.budget.roll_over(now)

        if self.budget.is_blocked(now):
            _LOGGER.debug(
                "DHL rate limit backoff active until %s, skipping this update",
                self.budget.backoff_until,
            )
            return self.states

        due = self._due_shipments(now)
        if not due:
            return self.states

        polled = 0
        for state in due:
            if not self.budget.has_capacity():
                _LOGGER.warning(
                    "Daily DHL request budget of %s requests is exhausted; "
                    "remaining shipments will be updated tomorrow",
                    self.budget.daily_budget,
                )
                break

            await self._async_throttle()
            await self._async_poll_shipment(state)
            polled += 1

            if self.budget.backoff_until is not None:
                # HTTP 429 - stop this cycle entirely.
                break

        if polled:
            self._persist()
        return self.states

    async def _async_throttle(self) -> None:
        """Keep at least ``min_seconds_between_calls`` between API calls."""
        if self._last_request_at is None or not self.min_seconds_between_calls:
            return
        elapsed = (dt_util.utcnow() - self._last_request_at).total_seconds()
        if (wait := self.min_seconds_between_calls - elapsed) > 0:
            await asyncio.sleep(wait)

    async def _async_poll_shipment(self, state: ShipmentState) -> None:
        """Fetch one shipment and update its state."""
        shipment = state.shipment
        self.budget.consume()
        self._last_request_at = dt_util.utcnow()
        state.last_polled = self._last_request_at

        try:
            data = await self.api.async_get_shipment(
                shipment.tracking_number,
                language=self.options.language,
                recipient_postal_code=shipment.recipient_postal_code,
            )
        except DhlAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except DhlRateLimitError as err:
            self.budget.note_rate_limited(dt_util.utcnow(), err.retry_after)
            _LOGGER.warning(
                "DHL API rate limit hit; pausing updates until %s",
                self.budget.backoff_until,
            )
            self._persist()
            return
        except DhlNotFoundError:
            state.error = "not_found"
            _LOGGER.debug(
                "DHL API reports no shipment for %s", shipment.tracking_number
            )
            return
        except DhlApiError as err:
            state.error = "api_error"
            _LOGGER.warning(
                "Could not update DHL shipment %s: %s", shipment.tracking_number, err
            )
            return

        self.budget.note_success()

        if data is None:
            state.error = "not_found"
            return

        state.error = None
        state.last_success = state.last_polled
        state.data = data
        self._async_handle_status(state, data)

    @callback
    def _async_handle_status(self, state: ShipmentState, data: dict[str, Any]) -> None:
        """Update the cached status and fire the status change event."""
        status_block = data.get("status") or {}
        new_status = status_block.get("status")
        new_status_code = status_block.get("statusCode")

        old_status = state.status
        old_status_code = state.status_code

        state.status = new_status
        state.status_code = new_status_code

        if (old_status, old_status_code) == (new_status, new_status_code):
            return

        first_result = old_status is None and old_status_code is None
        if first_result and state.tracking_number not in self._announce_first_status:
            # First payload for a shipment that was already known before this
            # Home Assistant start: not a real status change.
            return
        self._announce_first_status.discard(state.tracking_number)

        self.hass.bus.async_fire(
            EVENT_STATUS_CHANGED,
            {
                **_shipment_event_data(state.shipment),
                "old_status": old_status,
                "new_status": new_status,
                "old_status_code": old_status_code,
                "new_status_code": new_status_code,
            },
        )


def _shipment_event_data(shipment: Shipment) -> dict[str, Any]:
    """Return the event payload shared by all shipment events.

    Deliberately limited to the tracking number and the user chosen display
    name - no API key, no addresses and no other personal data.
    """
    return {
        "tracking_number": shipment.tracking_number,
        "name": shipment.display_name,
    }
