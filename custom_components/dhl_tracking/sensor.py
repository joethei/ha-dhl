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
from homeassistant.const import (
    MAX_LENGTH_STATE_STATE,
    EntityCategory,
    UnitOfMass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTRIBUTION,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
    REFERENCE_TYPE_PRIORITY,
    SENSITIVE_REFERENCE_SCOPES,
    SENSITIVE_REFERENCE_TYPES,
    STATUS_CODE_DELIVERED,
    STATUS_CODES,
)
from .coordinator import (
    DhlUpdateCoordinator,
    ShipmentPriority,
    ShipmentState,
    derive_status_code,
    parse_api_date,
    parse_api_datetime,
)
from .platform_helper import async_setup_shipment_platform
from .shipment_features import extract_features


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


def _iso(value: Any) -> str | None:
    """Return a timezone aware ISO string for an API date-time value.

    DHL sends the delivery window without a UTC offset (``2026-09-23T13:20:00``
    means 13:20 German local time). Those naive values are anchored in the time
    zone configured in Home Assistant, so templates and `as_timestamp` work
    without the dashboard having to guess the offset.
    """
    parsed = parse_api_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _delivery_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Return the full delivery forecast as attributes."""
    frame = _delivery_time_frame(data)
    remark = data.get("estimatedTimeOfDeliveryRemark")
    attrs = {
        "time_frame_from": _iso(frame.get("estimatedFrom")),
        "time_frame_through": _iso(frame.get("estimatedThrough")),
        "time_frame_remark": remark,
        "remark": remark,
        "raw_estimated_time_of_delivery": data.get("estimatedTimeOfDelivery"),
        "raw_time_frame_from": frame.get("estimatedFrom"),
        "raw_time_frame_through": frame.get("estimatedThrough"),
    }
    return {key: value for key, value in attrs.items() if value is not None}


def _person_name(entity: Any) -> str | None:
    """Return a readable name for a ``PersonEntity`` of any @type."""
    if not isinstance(entity, dict):
        return None
    if name := entity.get("name") or entity.get("organizationName"):
        return str(name)
    given = entity.get("givenName")
    family = entity.get("familyName")
    combined = " ".join(part for part in (given, family) if part)
    return combined or None


def _delivery_location(place: Any) -> dict[str, Any] | None:
    """Return where a shipment was handed over, from a ``SecuredPlace``."""
    if not isinstance(place, dict):
        return None

    location: dict[str, Any] = {}
    address = place.get("address")
    if isinstance(address, dict):
        for source, target in (
            ("addressLocality", "city"),
            ("postalCode", "postal_code"),
            ("streetAddress", "street"),
            ("countryCode", "country"),
            ("addressLocalityServicing", "locality_detail"),
        ):
            if (value := address.get(source)) is not None:
                location[target] = value

    service_point = place.get("servicePoint")
    if isinstance(service_point, dict):
        for source, target in (
            ("label", "service_point"),
            ("url", "service_point_url"),
        ):
            if (value := service_point.get(source)) is not None:
                location[target] = value

    return location or None


def _handover_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Return who took the parcel and where, once it has been delivered.

    Built from the documented ``details.proofOfDelivery`` object and the
    ``status.location`` place. Note that this can contain a neighbour's name -
    it is exposed because a dashboard needs it, but it is not put into events
    or logs.
    """
    status = data.get("status")
    status = status if isinstance(status, dict) else {}
    if status.get("statusCode") != STATUS_CODE_DELIVERED:
        # Before delivery there is nothing to report, and `details.receiver`
        # is the addressee rather than whoever accepted the parcel - using it
        # would both be a guess and leak the recipient's name for every
        # shipment in transit.
        return {}

    attrs: dict[str, Any] = {}
    details = data.get("details")
    details = details if isinstance(details, dict) else {}
    pod = details.get("proofOfDelivery")
    pod = pod if isinstance(pod, dict) else {}

    if (signed := _person_name(pod.get("signed"))) is not None:
        attrs["delivered_to"] = signed

    if (location := _delivery_location(status.get("location"))) is not None:
        attrs["delivery_location"] = location

    delivered_at = parse_api_datetime(pod.get("timestamp")) or parse_api_datetime(
        status.get("timestamp")
    )
    if delivered_at is not None:
        attrs["delivered_at"] = delivered_at.isoformat()

    if (url := pod.get("documentUrl")) is not None:
        attrs["proof_of_delivery_url"] = url

    return attrs


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


def _truncate(value: Any) -> Any:
    """Keep a sensor state within Home Assistant's 255 character limit.

    DHL's free text fields have no documented length limit, and Home Assistant
    refuses a longer state outright, which would leave the entity stuck. The
    full text stays available as the `full_value` attribute.
    """
    if isinstance(value, str) and len(value) > MAX_LENGTH_STATE_STATE:
        return value[: MAX_LENGTH_STATE_STATE - 1] + "\u2026"
    return value


def _references(data: dict[str, Any] | None) -> list[dict[str, str]]:
    """Return the publishable references of a shipment.

    Entries DHL marks as `secret` or `sensitive` via `@scope`, and the account
    number types, are dropped - they identify a billing account rather than
    the parcel.
    """
    details = (data or {}).get("details")
    details = details if isinstance(details, dict) else {}
    references = details.get("references")
    if not isinstance(references, list):
        return []

    result: list[dict[str, str]] = []
    for entry in references:
        if not isinstance(entry, dict):
            continue
        ref_type = entry.get("type")
        number = entry.get("number")
        if not ref_type or not number:
            continue
        if ref_type in SENSITIVE_REFERENCE_TYPES:
            continue
        if entry.get("@scope") in SENSITIVE_REFERENCE_SCOPES:
            continue
        result.append({"type": str(ref_type), "number": str(number)})
    return result


def _primary_reference(data: dict[str, Any] | None) -> str | None:
    """Return the reference most likely to match a webshop order."""
    references = _references(data)
    for wanted in REFERENCE_TYPE_PRIORITY:
        for entry in references:
            if entry["type"] == wanted:
                return entry["number"]
    return references[0]["number"] if references else None


def _status_text_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Return the status texts that do not get their own sensor."""
    status = data.get("status")
    status = status if isinstance(status, dict) else {}
    attrs = {
        "status_detailed": status.get("statusDetailed"),
        "status_remark": status.get("remark"),
        "next_steps": status.get("nextSteps"),
    }
    return {key: value for key, value in attrs.items() if value is not None}


def _summary_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Everything a dashboard needs next to the status code."""
    reroute_url = data.get("rerouteUrl")
    attrs = {
        **extract_features(data).as_attributes(),
        **_handover_attributes(data),
        **_status_text_attributes(data),
        # The unmodified API value, since `status_code` may report the derived
        # `out_for_delivery`.
        "status_code_api": _nested(data, "status", "statusCode"),
        "description": _nested(data, "status", "description"),
        "references": _references(data),
        "customer_reference": _primary_reference(data),
        # DHL only sends the reroute link while rerouting is actually possible
        # for the current status, so its presence is a signal in itself.
        "reroute_available": reroute_url is not None,
    }
    if reroute_url is not None:
        attrs["reroute_url"] = reroute_url
    return attrs


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
        value_fn=lambda data: derive_status_code(data, dt_util.utcnow()),
        extra_attrs_fn=_summary_attributes,
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
        extra_attrs_fn=_status_text_attributes,
    ),
    DhlSensorEntityDescription(
        key="next_steps",
        translation_key="next_steps",
        icon="mdi:arrow-right-circle-outline",
        value_fn=lambda data: _nested(data, "status", "nextSteps"),
    ),
    DhlSensorEntityDescription(
        key="customer_reference",
        translation_key="customer_reference",
        icon="mdi:receipt-text-outline",
        value_fn=_primary_reference,
        extra_attrs_fn=lambda data: {"references": _references(data)},
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
        extra_attrs_fn=lambda data: extract_features(data).as_attributes(),
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
        key="reroute_url",
        translation_key="reroute_url",
        icon="mdi:directions-fork",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rerouteUrl"),
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

    async_setup_shipment_platform(
        hass,
        entry,
        coordinator,
        async_add_entities,
        build=lambda tracking_number: [
            DhlShipmentSensor(coordinator, tracking_number, description)
            for description in SENSOR_DESCRIPTIONS
        ],
        extra=[
            DhlApiUsageSensor(coordinator),
            DhlOpenShipmentsSensor(coordinator),
            DhlNextDeliverySensor(coordinator),
        ],
    )


class DhlShipmentSensor(CoordinatorEntity[DhlUpdateCoordinator], SensorEntity):
    """A single field of a tracked DHL shipment."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    # The event history is long and changes on every update.
    _unrecorded_attributes = frozenset({"events"})
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

    def _raw_value(self) -> Any:
        """Return the untruncated value from the API payload."""
        state = self._state
        if state is None or state.data is None:
            return None
        return self.entity_description.value_fn(state.data)

    @property
    def native_value(self) -> Any:
        """Return the current value, capped to what Home Assistant accepts."""
        return _truncate(self._raw_value())

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
        state = self._state
        attrs: dict[str, Any] = {"tracking_number": self._tracking_number}
        if state is not None:
            # The bare shipment name, so a dashboard does not have to strip the
            # entity suffix off the friendly name.
            attrs["name"] = state.shipment.display_name
        if (
            state is not None
            and state.data is not None
            and (extra_fn := self.entity_description.extra_attrs_fn) is not None
        ):
            attrs.update(extra_fn(state.data))

        raw = self._raw_value()
        if isinstance(raw, str) and len(raw) > MAX_LENGTH_STATE_STATE:
            attrs["full_value"] = raw
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


class DhlEntrySensor(CoordinatorEntity[DhlUpdateCoordinator], SensorEntity):
    """Base for the per config entry summary sensors."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: DhlUpdateCoordinator, key: str) -> None:
        """Initialize the sensor."""
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

    def _open_states(self) -> list[ShipmentState]:
        """Return the shipments that have not been delivered yet."""
        return [
            state for state in self.coordinator.states.values() if not state.delivered
        ]


class DhlOpenShipmentsSensor(DhlEntrySensor):
    """How many shipments are still on their way, plus a compact overview."""

    _attr_icon = "mdi:package-variant-closed"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # A per-shipment list would bloat the database on every update.
    _unrecorded_attributes = frozenset({"shipments"})

    def __init__(self, coordinator: DhlUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "open_shipments")

    @property
    def native_value(self) -> int:
        """Return the number of shipments that are not delivered."""
        return len(self._open_states())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return one entry per open shipment."""
        shipments = []
        for state in self._open_states():
            data = state.data or {}
            frame = _delivery_time_frame(data)
            features = extract_features(data)
            delivery = _estimated_delivery_time(data)
            day = _estimated_delivery_day(data)
            shipments.append(
                {
                    "tracking_number": state.tracking_number,
                    "name": state.shipment.display_name,
                    "status_code": derive_status_code(data, dt_util.utcnow()),
                    "status": _nested(data, "status", "status"),
                    "description": _nested(data, "status", "description"),
                    "estimated_delivery": (
                        delivery.isoformat() if delivery is not None else None
                    ),
                    "estimated_delivery_date": day.isoformat() if day else None,
                    "time_frame_from": _iso(frame.get("estimatedFrom")),
                    "time_frame_through": _iso(frame.get("estimatedThrough")),
                    "signature_required": features.signature_required,
                    "id_required": features.id_required,
                    "services": list(features.services),
                    "customer_reference": _primary_reference(data),
                    "next_steps": _nested(data, "status", "nextSteps"),
                }
            )
        return {"shipments": shipments}


class DhlNextDeliverySensor(DhlEntrySensor):
    """The earliest delivery expected across all open shipments."""

    _attr_icon = "mdi:truck-delivery"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DhlUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "next_delivery")

    def _earliest_time(self) -> tuple[datetime, ShipmentState] | None:
        """Return the earliest precise delivery time, if any shipment has one."""
        candidates = [
            (moment, state)
            for state in self._open_states()
            if (moment := _estimated_delivery_time(state.data or {})) is not None
        ]
        return min(candidates, key=lambda item: item[0]) if candidates else None

    def _earliest_day(self) -> tuple[date, ShipmentState] | None:
        """Return the earliest known delivery day, even without a time."""
        candidates = [
            (day, state)
            for state in self._open_states()
            if (day := _estimated_delivery_day(state.data or {})) is not None
        ]
        return min(candidates, key=lambda item: item[0]) if candidates else None

    @property
    def native_value(self) -> datetime | None:
        """Return the earliest delivery time DHL actually committed to."""
        earliest = self._earliest_time()
        return earliest[0] if earliest is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return which shipment the value belongs to, plus the day level view.

        A German parcel usually only has a delivery *day*, so the day level
        attributes stay populated even when the timestamp above is empty.
        """
        attrs: dict[str, Any] = {}
        if (earliest := self._earliest_time()) is not None:
            attrs["tracking_number"] = earliest[1].tracking_number
            attrs["name"] = earliest[1].shipment.display_name
        if (earliest_day := self._earliest_day()) is not None:
            attrs["earliest_date"] = earliest_day[0].isoformat()
            attrs["earliest_date_tracking_number"] = earliest_day[1].tracking_number
            attrs["earliest_date_name"] = earliest_day[1].shipment.display_name
        return attrs
