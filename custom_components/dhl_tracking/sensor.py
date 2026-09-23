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
    CONF_API_KEY,
    CONF_TRACKING_NUMBERS,
    DEFAULT_SCAN_INTERVAL,
    SENSOR_TYPES,
    ATTR_TRACKING_NUMBER,
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

        # Create sensor entity for each API attribute
        for sensor_type, sensor_config in SENSOR_TYPES.items():
            entities.append(
                DHLTrackingSensor(
                    coordinator, tracking_number, sensor_type, sensor_config
                )
            )

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
            data = await self.hass.async_add_executor_job(
                self.tracker.get_shipment_status, self.tracking_number
            )
            if data is None:
                # Don't raise UpdateFailed for rate limits or missing data
                # to avoid excessive error logging
                _LOGGER.debug(
                    "No data returned for %s, keeping previous data",
                    self.tracking_number,
                )
                return self.data  # Return previous data if available
            return data
        except Exception as exc:
            if "rate limit" in str(exc).lower():
                _LOGGER.info(
                    "Rate limit reached for %s, will retry later", self.tracking_number
                )
                return self.data  # Return previous data on rate limit
            else:
                _LOGGER.error(
                    "Error fetching data for %s: %s", self.tracking_number, exc
                )
                raise UpdateFailed(f"Error fetching data: {exc}") from exc


class DHLTrackingSensor(CoordinatorEntity, SensorEntity):
    """DHL Tracking sensor for individual API attributes."""

    def __init__(
        self,
        coordinator: DHLTrackingCoordinator,
        tracking_number: str,
        sensor_type: str,
        sensor_config: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.tracking_number = tracking_number
        self.sensor_type = sensor_type
        self.sensor_config = sensor_config

        self._attr_name = f"DHL {tracking_number} {sensor_config['name']}"
        self._attr_unique_id = f"dhl_tracking_{tracking_number}_{sensor_type}"
        self._attr_icon = sensor_config["icon"]

        if sensor_config.get("device_class"):
            self._attr_device_class = sensor_config["device_class"]
        if sensor_config.get("unit"):
            self._attr_native_unit_of_measurement = sensor_config["unit"]

    def _get_nested_value(self, data: dict[str, Any], path: list[str]) -> Any:
        """Get value from nested dictionary using path."""
        value = data
        for key in path:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def _format_location(self, location_data: dict[str, Any]) -> str | None:
        """Format location data for display."""
        if not location_data:
            return None

        address = location_data.get("address", {})
        city = address.get("addressLocality", "")
        country = address.get("countryCode", "")

        if city and country:
            return f"{city}, {country}"
        elif city:
            return city
        elif country:
            return country
        else:
            return None

    @property
    def native_value(self) -> str | int | float | bool | None:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None

        data = self.coordinator.data
        api_path = self.sensor_config.get("api_path", [])

        if not api_path:
            return None

        # Special handling for specific sensor types
        if self.sensor_type == "status_location":
            # Get location from status
            status_location = self._get_nested_value(data, ["status", "location"])
            return self._format_location(status_location)

        elif self.sensor_type == "return_flag":
            # Handle boolean return flag
            value = self._get_nested_value(data, api_path)
            return "Ja" if value else "Nein"

        else:
            # Standard path extraction
            value = self._get_nested_value(data, api_path)

            # Handle weight unit display
            if self.sensor_type == "weight_unit" and value:
                return value
            elif self.sensor_type == "weight_value" and value:
                # For weight value, also get the unit for display
                unit = self._get_nested_value(data, ["details", "weight", "unitText"])
                if unit:
                    self._attr_native_unit_of_measurement = unit
                return value

            return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if self.coordinator.data is None:
            return None

        data = self.coordinator.data
        attributes = {
            ATTR_TRACKING_NUMBER: data.get("id"),
            ATTR_EVENTS: data.get("events"),
        }

        # Add raw API path data for debugging
        api_path = self.sensor_config.get("api_path", [])
        if api_path:
            attributes["api_path"] = " -> ".join(api_path)
            attributes["raw_value"] = self._get_nested_value(data, api_path)

        # Remove None values
        return {k: v for k, v in attributes.items() if v is not None}

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success
