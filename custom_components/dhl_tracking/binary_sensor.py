"""Binary sensor platform for the DHL Tracking integration.

Answers the questions several automations ask at once - "is a parcel coming
today?", "is something waiting at a Packstation?" - so that each of them does
not have to filter the shipment list with its own template.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, DEFAULT_NAME, DOMAIN, MANUFACTURER
from .coordinator import (
    DhlUpdateCoordinator,
    ShipmentState,
    forecast_day,
    pickup_wait,
)
from .pickup import is_ready_for_pickup, pickup_location
from .platform_helper import async_setup_shipment_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the summary binary sensors."""
    coordinator: DhlUpdateCoordinator = entry.runtime_data.coordinator

    async_setup_shipment_platform(
        hass,
        entry,
        coordinator,
        async_add_entities,
        build=lambda tracking_number: [],
        extra=[
            DhlDeliveryExpectedTodaySensor(coordinator),
            DhlPickupWaitingSensor(coordinator),
        ],
    )


def _is_waiting_for_pickup(state: ShipmentState) -> bool:
    return is_ready_for_pickup((state.data or {}).get("status"))


class DhlEntryBinarySensor(CoordinatorEntity[DhlUpdateCoordinator], BinarySensorEntity):
    """Base for the per config entry binary sensors."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    # The shipment list changes with every poll; recording it would bloat the
    # database for no benefit.
    _unrecorded_attributes = frozenset({"shipments"})

    def __init__(self, coordinator: DhlUpdateCoordinator, key: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=DEFAULT_NAME,
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://developer.dhl.com/api-reference/shipment-tracking",
        )

    @property
    def available(self) -> bool:
        """Summaries are computed locally and always available."""
        return True

    def _matching(self) -> list[ShipmentState]:
        raise NotImplementedError

    @property
    def is_on(self) -> bool:
        """Return whether any shipment matches."""
        return bool(self._matching())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return which shipments the state is about."""
        return {
            "shipments": [self._describe(state) for state in self._matching()],
        }

    def _describe(self, state: ShipmentState) -> dict[str, Any]:
        return {
            "tracking_number": state.tracking_number,
            "name": state.shipment.display_name,
        }


class DhlDeliveryExpectedTodaySensor(DhlEntryBinarySensor):
    """On while DHL expects to deliver at least one parcel today.

    Parcels waiting in a Packstation are left out: DHL keeps the day of the
    Packstation run in the forecast, but nothing is coming to the door.
    """

    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator: DhlUpdateCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "delivery_expected_today")

    async def async_added_to_hass(self) -> None:
        """Re-evaluate at midnight, when "today" moves on without a poll."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._async_midnight, hour=0, minute=0, second=0
            )
        )

    @callback
    def _async_midnight(self, _now: datetime) -> None:
        self.async_write_ha_state()

    def _matching(self) -> list[ShipmentState]:
        today = dt_util.now().date()
        return [
            state
            for state in self.coordinator.states.values()
            if not state.delivered
            and not _is_waiting_for_pickup(state)
            and forecast_day(state.data) == today
        ]


class DhlPickupWaitingSensor(DhlEntryBinarySensor):
    """On while a parcel waits in a Packstation or at a pickup point."""

    _attr_icon = "mdi:package-variant-closed-check"

    def __init__(self, coordinator: DhlUpdateCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "pickup_waiting")

    def _matching(self) -> list[ShipmentState]:
        return [
            state
            for state in self.coordinator.states.values()
            if not state.delivered and _is_waiting_for_pickup(state)
        ]

    def _describe(self, state: ShipmentState) -> dict[str, Any]:
        location = pickup_location((state.data or {}).get("status")) or {}
        return {
            **super()._describe(state),
            "pickup_location": location.get("label"),
            **pickup_wait(state.data, dt_util.utcnow()),
        }
