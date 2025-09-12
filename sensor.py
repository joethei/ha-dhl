"""DHL Tracking sensor platform."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_TRACKING_NUMBERS,
    DEFAULT_SCAN_INTERVAL,
    ATTR_TRACKING_NUMBER,
    ATTR_PRODUCT,
    ATTR_TOTAL_PIECES,
    ATTR_WEIGHT,
    ATTR_ORIGIN,
    ATTR_DESTINATION,
    ATTR_SERVICE_URL,
    ATTR_STATUS_CODE,
    ATTR_STATUS_TIMESTAMP,
    ATTR_STATUS_DESCRIPTION,
    ATTR_EVENTS,
)
from .dhl_tracker import DHLTracker

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHL Tracking sensors."""
    api_key = config_entry.data[CONF_API_KEY]
    tracking_numbers = config_entry.data.get(CONF_TRACKING_NUMBERS, [])
    
    # Ensure tracking_numbers is a list
    if isinstance(tracking_numbers, str):
        tracking_numbers = [tracking_numbers]
    elif not isinstance(tracking_numbers, list):
        tracking_numbers = []
    
    _LOGGER.debug("Setting up sensors for tracking numbers: %s", tracking_numbers)

    if not tracking_numbers:
        _LOGGER.warning("No tracking numbers configured")
        return

    tracker = DHLTracker(api_key)

    # Create coordinator for each tracking number
    coordinators = []
    entities = []

    for tracking_number in tracking_numbers:
        coordinator = DHLTrackingCoordinator(hass, tracker, tracking_number)
        coordinators.append(coordinator)

        # Fetch initial data
        await coordinator.async_config_entry_first_refresh()

        # Create sensor entity
        entities.append(DHLTrackingSensor(coordinator, tracking_number))

    async_add_entities(entities)


class DHLTrackingCoordinator(DataUpdateCoordinator):
    """Class to manage fetching DHL tracking data."""

    def __init__(
        self, hass: HomeAssistant, tracker: DHLTracker, tracking_number: str
    ) -> None:
        """Initialize the coordinator."""
        self.tracker = tracker
        self.tracking_number = tracking_number

        super().__init__(
            hass,
            _LOGGER,
            name=f"DHL Tracking {tracking_number}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any] | None:
        """Fetch data from DHL API."""
        try:
            return await self.hass.async_add_executor_job(
                self.tracker.get_shipment_status, self.tracking_number
            )
        except Exception as exc:
            raise UpdateFailed(f"Error fetching data: {exc}") from exc


class DHLTrackingSensor(CoordinatorEntity, SensorEntity):
    """DHL Tracking sensor."""

    def __init__(
        self, coordinator: DHLTrackingCoordinator, tracking_number: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.tracking_number = tracking_number
        self._attr_name = f"DHL Tracking {tracking_number}"
        self._attr_unique_id = f"dhl_tracking_{tracking_number}"
        self._attr_icon = "mdi:package-variant-closed"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("status", "Unknown")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if self.coordinator.data is None:
            return None

        data = self.coordinator.data
        attributes = {
            ATTR_TRACKING_NUMBER: data.get("tracking_number"),
            ATTR_PRODUCT: data.get("product"),
            ATTR_TOTAL_PIECES: data.get("total_pieces"),
            ATTR_WEIGHT: data.get("weight"),
            ATTR_ORIGIN: data.get("origin"),
            ATTR_DESTINATION: data.get("destination"),
            ATTR_SERVICE_URL: data.get("service_url"),
            ATTR_STATUS_CODE: data.get("status_code"),
            ATTR_STATUS_TIMESTAMP: data.get("status_timestamp"),
            ATTR_STATUS_DESCRIPTION: data.get("description"),
            ATTR_EVENTS: data.get("events"),
        }

        # Remove None values
        return {k: v for k, v in attributes.items() if v is not None}

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success
