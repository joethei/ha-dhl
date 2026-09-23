"""Event entities for the DHL Tracking integration.

One event entity per shipment, so automations can trigger on a status change
without listening on the bus. The event types mirror the status codes the
integration reports, including the derived ``out_for_delivery``.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTRIBUTION,
    DOMAIN,
    MANUFACTURER,
    STATUS_CODE_UNKNOWN,
    STATUS_CODES,
)
from .coordinator import DhlUpdateCoordinator, ShipmentState
from .platform_helper import async_setup_shipment_platform

# Home Assistant event types may not contain a dash.
EVENT_TYPES: list[str] = [code.replace("-", "_") for code in STATUS_CODES]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the status and the scan event entity per shipment."""
    coordinator: DhlUpdateCoordinator = entry.runtime_data.coordinator

    async_setup_shipment_platform(
        hass,
        entry,
        coordinator,
        async_add_entities,
        build=lambda tracking_number: [
            DhlShipmentEvent(coordinator, tracking_number),
            DhlShipmentScanEvent(coordinator, tracking_number),
        ],
    )


class DhlShipmentEvent(EventEntity):
    """Fires whenever the status of one shipment really changes."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_translation_key = "shipment_status"
    _attr_icon = "mdi:package-variant"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: DhlUpdateCoordinator, tracking_number: str) -> None:
        """Initialize the entity."""
        self.coordinator = coordinator
        self._tracking_number = tracking_number
        self._attr_unique_id = f"{DOMAIN}_{tracking_number}_status_event"

        shipment = coordinator.states[tracking_number].shipment
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tracking_number)},
            name=shipment.display_name,
            manufacturer=MANUFACTURER,
            serial_number=tracking_number,
            via_device=(DOMAIN, coordinator.config_entry.entry_id),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to status changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_status_listener(self._async_handle_status)
        )

    @callback
    def _async_handle_status(
        self, state: ShipmentState, payload: dict[str, Any]
    ) -> None:
        """Trigger the event for a real status change of *this* shipment.

        The coordinator only calls its status listeners for genuine changes,
        so restarting Home Assistant does not replay an event.
        """
        if state.tracking_number != self._tracking_number:
            return
        new_code = payload.get("new_status_code") or STATUS_CODE_UNKNOWN
        event_type = new_code.replace("-", "_")
        if event_type not in EVENT_TYPES:
            event_type = STATUS_CODE_UNKNOWN
        self._trigger_event(
            event_type,
            {
                "tracking_number": payload.get("tracking_number"),
                "name": payload.get("name"),
                "old_status_code": payload.get("old_status_code"),
                "new_status_code": payload.get("new_status_code"),
                "description": payload.get("description"),
            },
        )
        self.async_write_ha_state()


class DhlShipmentScanEvent(EventEntity):
    """Fires for every new tracking scan, not only on a status change.

    The five documented status codes collapse a lot of detail: a parcel can
    be announced, processed, arrive in the destination region and be loaded
    into the delivery vehicle while `statusCode` stays `transit` throughout.
    This entity fires for each of those scans; the division specific code
    (`VA`, `AA`, `EE`, `PO`, ...) rides along as an attribute rather than as
    an event type, because DHL documents neither the list nor its stability.
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_translation_key = "shipment_scan"
    _attr_icon = "mdi:map-marker-path"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: DhlUpdateCoordinator, tracking_number: str) -> None:
        """Initialize the entity."""
        self.coordinator = coordinator
        self._tracking_number = tracking_number
        self._attr_unique_id = f"{DOMAIN}_{tracking_number}_scan_event"

        shipment = coordinator.states[tracking_number].shipment
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tracking_number)},
            name=shipment.display_name,
            manufacturer=MANUFACTURER,
            serial_number=tracking_number,
            via_device=(DOMAIN, coordinator.config_entry.entry_id),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracking scans."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_scan_listener(self._async_handle_scan)
        )

    @callback
    def _async_handle_scan(self, state: ShipmentState, payload: dict[str, Any]) -> None:
        """Trigger the event for a scan of *this* shipment."""
        if state.tracking_number != self._tracking_number:
            return
        code = payload.get("status_code") or STATUS_CODE_UNKNOWN
        event_type = code.replace("-", "_")
        if event_type not in EVENT_TYPES:
            event_type = STATUS_CODE_UNKNOWN
        self._trigger_event(
            event_type,
            {
                "tracking_number": payload.get("tracking_number"),
                "name": payload.get("name"),
                "status": payload.get("status"),
                "status_code": payload.get("status_code"),
                "status_detailed": payload.get("status_detailed"),
                "description": payload.get("description"),
                "location": payload.get("location"),
                "timestamp": payload.get("timestamp"),
            },
        )
        self.async_write_ha_state()
