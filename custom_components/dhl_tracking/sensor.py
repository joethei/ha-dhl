"""Sensor platform for the DHL Tracking integration.

One device per shipment; the sensors map onto the fields of the
``TrackingShipment`` schema of the official Unified Shipment Tracking API.

Entity unique ids keep the historic ``dhl_tracking_<number>_<key>`` format so
that existing installations keep their entity ids after the update.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
    STATUS_CODE_UNKNOWN,
    STATUS_CODES,
)
from .coordinator import (
    DhlUpdateCoordinator,
    ShipmentDiff,
    ShipmentPriority,
    ShipmentState,
    parse_api_date,
    parse_api_datetime,
)


def _minutes(coordinator: DhlUpdateCoordinator, priority: ShipmentPriority) -> int:
    """Return the effective poll interval of a priority, in whole minutes."""
    interval = max(
        coordinator.priority_floor(priority),
        coordinator.fair_share_interval(priority),
    )
    return round(interval.total_seconds() / 60)


_LOGGER = logging.getLogger(__name__)

# Number of history events exposed as an attribute of the status sensor.
MAX_EVENTS = 10

RETURN_FLAG_OPTIONS = ["yes", "no"]

WEIGHT_UNITS: dict[str, str] = {
    "kg": UnitOfMass.KILOGRAMS,
    "kgs": UnitOfMass.KILOGRAMS,
    "kilogram": UnitOfMass.KILOGRAMS,
    "g": UnitOfMass.GRAMS,
    "gram": UnitOfMass.GRAMS,
    "lb": UnitOfMass.POUNDS,
    "lbs": UnitOfMass.POUNDS,
    "pound": UnitOfMass.POUNDS,
    "oz": UnitOfMass.OUNCES,
}


def _nested(data: dict[str, Any] | None, *path: str) -> Any:
    """Return a nested value from the API payload, or ``None``."""
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _format_place(place: Any) -> str | None:
    """Return ``City, CC`` for a ``SecuredPlace``.

    Street level details are deliberately dropped - they are not needed for
    automations and would leak the delivery address into the state machine.
    """
    address = _nested(place, "address") if isinstance(place, dict) else None
    if not isinstance(address, dict):
        return None
    city = address.get("addressLocality")
    country = address.get("countryCode")
    if city and country:
        return f"{city}, {country}"
    return city or country or None


def _enum(
    value: Any, allowed: list[str] | tuple[str, ...], fallback: str | None
) -> str | None:
    """Clamp an API value onto the documented enum options."""
    if value is None:
        return None
    text = str(value)
    if text in allowed:
        return text
    _LOGGER.debug("Unexpected DHL enum value %r, reporting %r", text, fallback)
    return fallback


def _weight_unit(data: dict[str, Any] | None) -> str | None:
    """Return the Home Assistant mass unit reported for the shipment."""
    raw = _nested(data, "details", "weight", "unitText")
    if not isinstance(raw, str):
        return None
    return WEIGHT_UNITS.get(raw.strip().lower())


def _delivery_time_frame(data: dict[str, Any] | None) -> dict[str, Any]:
    """Return the ``estimatedDeliveryTimeFrame`` object, or an empty dict."""
    frame = (data or {}).get("estimatedDeliveryTimeFrame")
    return frame if isinstance(frame, dict) else {}


def _has_time_of_day(value: datetime) -> bool:
    """Return whether a timestamp carries a meaningful time.

    DHL sends the estimated delivery as ``format: date-time`` even when it
    only knows the day, in which case the time reads ``00:00:00``. Parcels are
    not delivered at midnight, so that is treated as "day only" rather than
    shown as a delivery time.
    """
    return (value.hour, value.minute, value.second) != (0, 0, 0)


def _estimated_delivery_time(data: dict[str, Any]) -> datetime | None:
    """Return a real point in time for the delivery, if DHL supplied one."""
    frame = _delivery_time_frame(data)
    if (start := parse_api_datetime(frame.get("estimatedFrom"))) is not None:
        return start
    eta = parse_api_datetime(data.get("estimatedTimeOfDelivery"))
    if eta is not None and _has_time_of_day(eta):
        return eta
    return None


def _estimated_delivery_day(data: dict[str, Any]) -> date | None:
    """Return the calendar day DHL expects to deliver on."""
    frame = _delivery_time_frame(data)
    return parse_api_date(frame.get("estimatedFrom")) or parse_api_date(
        data.get("estimatedTimeOfDelivery")
    )


def _delivery_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Return the full delivery forecast as attributes."""
    frame = _delivery_time_frame(data)
    attrs = {
        "time_frame_from": frame.get("estimatedFrom"),
        "time_frame_through": frame.get("estimatedThrough"),
        "remark": data.get("estimatedTimeOfDeliveryRemark"),
        "raw_estimated_time_of_delivery": data.get("estimatedTimeOfDelivery"),
    }
    return {key: value for key, value in attrs.items() if value is not None}


@dataclass(frozen=True, kw_only=True)
class DhlSensorEntityDescription(SensorEntityDescription):
    """Describes a DHL shipment sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    unit_fn: Callable[[dict[str, Any] | None], str | None] | None = None
    extra_attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _status_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Return the trimmed event history for the status sensor."""
    events = data.get("events")
    if not isinstance(events, list):
        return {}
    history = []
    for event in events[:MAX_EVENTS]:
        if not isinstance(event, dict):
            continue
        entry = {
            "timestamp": event.get("timestamp"),
            "status": event.get("status"),
            "status_code": event.get("statusCode"),
            "description": event.get("description"),
            "location": _format_place(event.get("location")),
        }
        history.append({k: v for k, v in entry.items() if v is not None})
    return {"events": history} if history else {}


SENSOR_DESCRIPTIONS: tuple[DhlSensorEntityDescription, ...] = (
    DhlSensorEntityDescription(
        key="status",
        translation_key="status",
        icon="mdi:package-variant-closed",
        value_fn=lambda data: _nested(data, "status", "status"),
        extra_attrs_fn=_status_attributes,
    ),
    DhlSensorEntityDescription(
        key="status_code",
        translation_key="status_code",
        device_class=SensorDeviceClass.ENUM,
        options=list(STATUS_CODES),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _enum(
            _nested(data, "status", "statusCode"), STATUS_CODES, STATUS_CODE_UNKNOWN
        ),
    ),
    DhlSensorEntityDescription(
        key="status_timestamp",
        translation_key="status_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: parse_api_datetime(_nested(data, "status", "timestamp")),
    ),
    DhlSensorEntityDescription(
        key="status_description",
        translation_key="status_description",
        icon="mdi:text",
        value_fn=lambda data: _nested(data, "status", "description"),
    ),
    DhlSensorEntityDescription(
        key="status_location",
        translation_key="status_location",
        icon="mdi:map-marker",
        value_fn=lambda data: _format_place(_nested(data, "status", "location")),
    ),
    DhlSensorEntityDescription(
        key="service",
        translation_key="service",
        icon="mdi:truck",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("service"),
    ),
    DhlSensorEntityDescription(
        key="product_name",
        translation_key="product_name",
        icon="mdi:package",
        value_fn=lambda data: _nested(data, "details", "product", "productName"),
    ),
    DhlSensorEntityDescription(
        key="total_pieces",
        translation_key="total_pieces",
        icon="mdi:package-variant",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _nested(data, "details", "totalNumberOfPieces"),
    ),
    DhlSensorEntityDescription(
        key="weight_value",
        translation_key="weight_value",
        device_class=SensorDeviceClass.WEIGHT,
        value_fn=lambda data: (
            _nested(data, "details", "weight", "value")
            if _weight_unit(data) is not None
            else None
        ),
        unit_fn=_weight_unit,
    ),
    DhlSensorEntityDescription(
        key="weight_unit",
        translation_key="weight_unit",
        icon="mdi:scale",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "details", "weight", "unitText"),
    ),
    DhlSensorEntityDescription(
        key="origin_country",
        translation_key="origin_country",
        icon="mdi:flag",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "origin", "address", "countryCode"),
    ),
    DhlSensorEntityDescription(
        key="origin_city",
        translation_key="origin_city",
        icon="mdi:city",
        value_fn=lambda data: _nested(data, "origin", "address", "addressLocality"),
    ),
    DhlSensorEntityDescription(
        key="destination_country",
        translation_key="destination_country",
        icon="mdi:flag-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _nested(data, "destination", "address", "countryCode"),
    ),
    DhlSensorEntityDescription(
        key="destination_city",
        translation_key="destination_city",
        icon="mdi:city-variant",
        value_fn=lambda data: _nested(
            data, "destination", "address", "addressLocality"
        ),
    ),
    DhlSensorEntityDescription(
        key="pickup_date",
        translation_key="pickup_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            pickup
            if (pickup := parse_api_datetime(data.get("pickUpDate"))) is not None
            and _has_time_of_day(pickup)
            else None
        ),
    ),
    DhlSensorEntityDescription(
        key="pickup_day",
        translation_key="pickup_day",
        icon="mdi:calendar-start",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: parse_api_date(data.get("pickUpDate")),
    ),
    DhlSensorEntityDescription(
        key="estimated_delivery",
        translation_key="estimated_delivery",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_estimated_delivery_time,
        extra_attrs_fn=_delivery_attributes,
    ),
    DhlSensorEntityDescription(
        key="estimated_delivery_date",
        translation_key="estimated_delivery_date",
        icon="mdi:calendar-check",
        device_class=SensorDeviceClass.DATE,
        value_fn=_estimated_delivery_day,
        extra_attrs_fn=_delivery_attributes,
    ),
    DhlSensorEntityDescription(
        key="delivery_remark",
        translation_key="delivery_remark",
        icon="mdi:calendar-text",
        value_fn=lambda data: data.get("estimatedTimeOfDeliveryRemark"),
    ),
    DhlSensorEntityDescription(
        key="service_url",
        translation_key="service_url",
        icon="mdi:web",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("serviceUrl"),
    ),
    DhlSensorEntityDescription(
        key="return_flag",
        translation_key="return_flag",
        icon="mdi:keyboard-return",
        device_class=SensorDeviceClass.ENUM,
        options=RETURN_FLAG_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            None
            if data.get("returnFlag") is None
            else ("yes" if data.get("returnFlag") else "no")
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the DHL Tracking sensors and keep them in sync at runtime."""
    coordinator: DhlUpdateCoordinator = entry.runtime_data.coordinator
    created: dict[str, list[DhlShipmentSensor]] = {}

    @callback
    def _build(tracking_number: str) -> list[DhlShipmentSensor]:
        entities = [
            DhlShipmentSensor(coordinator, tracking_number, description)
            for description in SENSOR_DESCRIPTIONS
        ]
        created[tracking_number] = entities
        return entities

    initial: list[SensorEntity] = [DhlApiUsageSensor(coordinator)]
    for tracking_number in coordinator.states:
        initial.extend(_build(tracking_number))
    async_add_entities(initial)

    async def _async_handle_shipment_diff(diff: ShipmentDiff) -> None:
        """Add or remove entities when the shipment list changed."""
        registry = er.async_get(hass)
        for shipment in diff.removed:
            for entity in created.pop(shipment.tracking_number, []):
                entity_id = entity.entity_id
                await entity.async_remove(force_remove=True)
                if entity_id and registry.async_get(entity_id) is not None:
                    registry.async_remove(entity_id)

        new_entities: list[SensorEntity] = []
        for shipment in diff.added:
            new_entities.extend(_build(shipment.tracking_number))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        coordinator.async_add_shipment_listener(_async_handle_shipment_diff)
    )


class DhlShipmentSensor(CoordinatorEntity[DhlUpdateCoordinator], SensorEntity):
    """A single field of a tracked DHL shipment."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    entity_description: DhlSensorEntityDescription

    def __init__(
        self,
        coordinator: DhlUpdateCoordinator,
        tracking_number: str,
        description: DhlSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._tracking_number = tracking_number
        # Historic format - do not change, it keeps existing entity ids.
        self._attr_unique_id = f"{DOMAIN}_{tracking_number}_{description.key}"

        shipment = coordinator.states[tracking_number].shipment
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tracking_number)},
            name=shipment.display_name,
            manufacturer=MANUFACTURER,
            serial_number=tracking_number,
            via_device=(DOMAIN, coordinator.config_entry.entry_id),
            configuration_url=(
                "https://www.dhl.com/de-de/home/tracking.html"
                f"?tracking-id={tracking_number}"
            ),
        )

    @property
    def _state(self) -> ShipmentState | None:
        """Return the runtime state of this shipment."""
        return self.coordinator.states.get(self._tracking_number)

    @property
    def available(self) -> bool:
        """Return True when the shipment has data from the API."""
        state = self._state
        return (
            self.coordinator.last_update_success
            and state is not None
            and state.available
        )

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        state = self._state
        if state is None or state.data is None:
            return None
        return self.entity_description.value_fn(state.data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, which can depend on the API payload."""
        if (unit_fn := self.entity_description.unit_fn) is not None:
            state = self._state
            return unit_fn(state.data if state else None)
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes."""
        attrs: dict[str, Any] = {"tracking_number": self._tracking_number}
        state = self._state
        if (
            state is not None
            and state.data is not None
            and (extra_fn := self.entity_description.extra_attrs_fn) is not None
        ):
            attrs.update(extra_fn(state.data))
        return attrs


class DhlApiUsageSensor(CoordinatorEntity[DhlUpdateCoordinator], SensorEntity):
    """Diagnostic sensor reporting the API requests spent today."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "api_requests_today"
    _attr_icon = "mdi:api"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: DhlUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_api_requests_today"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=DEFAULT_NAME,
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://developer.dhl.com/api-reference/shipment-tracking",
        )

    @property
    def available(self) -> bool:
        """This sensor reports local bookkeeping and is always available."""
        return True

    @property
    def native_value(self) -> int:
        """Return the number of API requests spent today."""
        return self.coordinator.budget.count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about the request budget."""
        coordinator = self.coordinator
        backoff = coordinator.budget.backoff_until
        counts = coordinator.priority_counts()
        return {
            "daily_budget": coordinator.budget.daily_budget,
            "remaining_today": coordinator.budget.remaining,
            "tracked_shipments": len(coordinator.states),
            "active_shipments": coordinator.active_count(),
            "delivered_shipments": coordinator.delivered_count(),
            "imminent_shipments": counts[ShipmentPriority.IMMINENT],
            "transit_shipments": counts[ShipmentPriority.TRANSIT],
            "pre_transit_shipments": counts[ShipmentPriority.PRE_TRANSIT],
            "interval_minutes_imminent": _minutes(
                coordinator, ShipmentPriority.IMMINENT
            ),
            "interval_minutes_transit": _minutes(coordinator, ShipmentPriority.TRANSIT),
            "interval_minutes_pre_transit": _minutes(
                coordinator, ShipmentPriority.PRE_TRANSIT
            ),
            "estimated_requests_per_day": round(
                coordinator.estimated_daily_requests(), 1
            ),
            "rate_limit_backoff_until": backoff.isoformat() if backoff else None,
        }
