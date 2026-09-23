"""Entity behaviour tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dhl_tracking.const import (
    DOMAIN,
    SERVICE_ADD_SHIPMENT,
    SERVICE_REMOVE_SHIPMENT,
)
from custom_components.dhl_tracking.sensor import SENSOR_DESCRIPTIONS
from homeassistant.components.sensor import (
    ATTR_STATE_CLASS,
    SensorDeviceClass,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    EntityCategory,
    UnitOfMass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import OTHER_TRACKING_NUMBER, TRACKING_NUMBER, shipment_payload


async def test_sensor_values(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The sensors expose the documented API fields."""
    await setup_integration(hass, mock_config_entry)

    assert hass.states.get("sensor.testpaket_status").state == "In transit"
    assert hass.states.get("sensor.testpaket_status_code").state == "transit"
    assert hass.states.get("sensor.testpaket_product").state == "DHL Paket"
    assert hass.states.get("sensor.testpaket_service").state == "parcel-de"
    assert hass.states.get("sensor.testpaket_origin_city").state == "Berlin"
    assert hass.states.get("sensor.testpaket_destination_country").state == "DE"
    assert hass.states.get("sensor.testpaket_status_location").state == "Hamburg, DE"
    assert hass.states.get("sensor.testpaket_return_shipment").state == "no"
    assert hass.states.get("sensor.testpaket_number_of_pieces").state == "1"


async def test_timestamp_sensors_are_datetimes(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Timestamp sensors expose parseable, timezone aware values."""
    await setup_integration(hass, mock_config_entry)

    for entity_id in (
        "sensor.testpaket_status_timestamp",
        "sensor.testpaket_pickup_date",
        "sensor.testpaket_estimated_delivery",
    ):
        state = hass.states.get(entity_id)
        assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.TIMESTAMP
        parsed = dt_util.parse_datetime(state.state)
        assert parsed is not None
        assert parsed.tzinfo is not None


async def test_naive_timestamps_get_a_timezone(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """API values without a UTC offset are interpreted in the local zone."""
    payload = shipment_payload(TRACKING_NUMBER, timestamp="2026-09-20T09:15:00")
    shipment_responses[TRACKING_NUMBER] = payload
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    state = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_status_timestamp")
    parsed = dt_util.parse_datetime(state.state)
    assert parsed is not None
    assert parsed.tzinfo is not None


async def test_weight_uses_a_home_assistant_unit(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The weight sensor maps the API unit onto a real mass unit."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get("sensor.testpaket_weight")
    assert state.state == "2.5"
    assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.WEIGHT
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UnitOfMass.KILOGRAMS


async def test_weight_with_unknown_unit_is_unknown(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """An unmappable weight unit yields no value instead of a broken sensor."""
    payload = shipment_payload(TRACKING_NUMBER)
    payload["details"]["weight"] = {"value": 3, "unitText": "stones"}
    shipment_responses[TRACKING_NUMBER] = payload
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    state = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_weight")
    assert state.state == "unknown"


async def test_unknown_status_code_is_clamped(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """An enum value outside the documented options falls back to 'unknown'."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status_code="teleported"
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    state = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_status_code")
    assert state.state == "unknown"


async def test_unique_ids_and_device_grouping(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Every sensor has a stable unique id and belongs to the shipment device."""
    await setup_integration(hass, mock_config_entry)
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    device = device_registry.async_get_device(identifiers={(DOMAIN, TRACKING_NUMBER)})
    assert device is not None
    assert device.name == "Testpaket"
    assert device.serial_number == TRACKING_NUMBER

    shipment_entities = [
        entity
        for entity in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
        if entity.device_id == device.id
    ]
    assert len(shipment_entities) == len(SENSOR_DESCRIPTIONS)
    expected = {
        f"{DOMAIN}_{TRACKING_NUMBER}_{description.key}"
        for description in SENSOR_DESCRIPTIONS
    }
    assert {entity.unique_id for entity in shipment_entities} == expected


async def test_diagnostic_entity_categories(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Technical sensors are marked as diagnostic."""
    await setup_integration(hass, mock_config_entry)
    entity_registry = er.async_get(hass)

    diagnostic = {
        entity.unique_id.rsplit("_", 1)[-1]
        for entity in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
        if entity.entity_category is EntityCategory.DIAGNOSTIC
    }
    assert "code" in diagnostic  # status_code
    assert entity_registry.async_get("sensor.testpaket_status").entity_category is None


async def test_service_device_and_api_usage_sensor(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The per-entry service device reports the request budget."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get("sensor.dhl_tracking_api_requests_today")
    assert state is not None
    assert state.state == "1"
    assert state.attributes["daily_budget"] == 200
    assert state.attributes["remaining_today"] == 199
    assert state.attributes["active_shipments"] == 1
    assert state.attributes[ATTR_STATE_CLASS] == "total_increasing"

    device_registry = dr.async_get(hass)
    service_device = device_registry.async_get_device(
        identifiers={(DOMAIN, mock_config_entry.entry_id)}
    )
    assert service_device is not None
    shipment_device = device_registry.async_get_device(
        identifiers={(DOMAIN, TRACKING_NUMBER)}
    )
    assert shipment_device.via_device_id == service_device.id


async def test_entities_appear_and_disappear_at_runtime(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Adding and removing a shipment creates and drops its entities."""
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.ersatzteil_status") is None

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Ersatzteil"},
        blocking=True,
    )
    await hass.async_block_till_done()

    created = [
        entity_id
        for entity_id in hass.states.async_entity_ids("sensor")
        if entity_id.startswith("sensor.ersatzteil_")
    ]
    assert len(created) == len(SENSOR_DESCRIPTIONS)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REMOVE_SHIPMENT,
        {"tracking_number": OTHER_TRACKING_NUMBER},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert not [
        entity_id
        for entity_id in hass.states.async_entity_ids("sensor")
        if entity_id.startswith("sensor.ersatzteil_")
    ]
    # The shipment that was there before is untouched.
    assert hass.states.get("sensor.testpaket_status") is not None


async def test_entities_unavailable_without_data(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A shipment the API does not know about reports unavailable."""
    shipment_responses[TRACKING_NUMBER] = None
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    state = hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_status")
    assert state.state == STATE_UNAVAILABLE


async def test_status_sensor_exposes_sanitised_events(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The event history is trimmed to city level, no street addresses."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get("sensor.testpaket_status")
    events = state.attributes["events"]
    assert len(events) == 1
    assert events[0]["location"] == "Hamburg, DE"
    assert set(events[0]) <= {
        "timestamp",
        "status",
        "status_code",
        "description",
        "location",
    }


async def test_device_name_follows_the_display_name(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Renaming a shipment renames the device without touching entities."""
    await setup_integration(hass, mock_config_entry)
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, TRACKING_NUMBER)})
    assert device.name == "Testpaket"

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_shipment"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"selected": TRACKING_NUMBER}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Umbenannt"}
    )
    await hass.async_block_till_done()

    device = device_registry.async_get_device(identifiers={(DOMAIN, TRACKING_NUMBER)})
    assert device.name == "Umbenannt"
    # The entity ids are derived from the original name and stay stable.
    assert hass.states.get("sensor.testpaket_status") is not None


def test_sensor_description_keys_are_stable() -> None:
    """Guard the documented sensor set and its unique id suffixes."""
    assert [description.key for description in SENSOR_DESCRIPTIONS] == [
        "status",
        "status_code",
        "status_timestamp",
        "status_description",
        "status_location",
        "service",
        "product_name",
        "total_pieces",
        "weight_value",
        "weight_unit",
        "origin_country",
        "origin_city",
        "destination_country",
        "destination_city",
        "pickup_date",
        "pickup_day",
        "estimated_delivery",
        "estimated_delivery_date",
        "delivery_remark",
        "service_url",
        "return_flag",
    ]


# --- Delivery forecast rendering ---------------------------------------------


async def test_date_only_forecast_does_not_invent_a_time(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A day without a time must not render as "at 00:00"."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, estimated_delivery="2026-09-23"
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    prefix = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
    # The timestamp sensor stays empty instead of claiming midnight.
    assert hass.states.get(f"{prefix}_estimated_delivery").state == "unknown"
    # The day is reported by its own date sensor.
    day = hass.states.get(f"{prefix}_delivery_day")
    assert day.state == "2026-09-23"
    assert day.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.DATE


async def test_midnight_forecast_is_treated_as_date_only(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """DHL sends 00:00:00 when it only knows the day - do not show it."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, estimated_delivery="2026-09-23T00:00:00+02:00"
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    prefix = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
    assert hass.states.get(f"{prefix}_estimated_delivery").state == "unknown"
    assert hass.states.get(f"{prefix}_delivery_day").state == "2026-09-23"


async def test_real_delivery_time_is_kept(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """When DHL does supply a time, the timestamp sensor still shows it."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, estimated_delivery="2026-09-23T14:30:00+02:00"
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    prefix = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
    state = hass.states.get(f"{prefix}_estimated_delivery")
    assert dt_util.parse_datetime(state.state) == dt_util.parse_datetime(
        "2026-09-23T14:30:00+02:00"
    )
    assert hass.states.get(f"{prefix}_delivery_day").state == "2026-09-23"


async def test_delivery_time_frame_wins_over_the_bare_date(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The delivery window is the most precise forecast DHL offers."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER,
        estimated_delivery="2026-09-23T00:00:00+02:00",
        delivery_time_frame={
            "estimatedFrom": "2026-09-23T10:00:00+02:00",
            "estimatedThrough": "2026-09-23T14:00:00+02:00",
        },
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    prefix = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
    state = hass.states.get(f"{prefix}_estimated_delivery")
    assert dt_util.parse_datetime(state.state) == dt_util.parse_datetime(
        "2026-09-23T10:00:00+02:00"
    )
    assert state.attributes["time_frame_from"] == "2026-09-23T10:00:00+02:00"
    assert state.attributes["time_frame_through"] == "2026-09-23T14:00:00+02:00"
    assert hass.states.get(f"{prefix}_delivery_day").state == "2026-09-23"


async def test_delivery_remark_sensor(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The human readable forecast from DHL gets its own sensor."""
    payload = shipment_payload(TRACKING_NUMBER)
    payload["estimatedTimeOfDeliveryRemark"] = "Zustellung heute zwischen 10 und 14 Uhr"
    shipment_responses[TRACKING_NUMBER] = payload
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    prefix = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
    assert (
        hass.states.get(f"{prefix}_delivery_forecast").state
        == "Zustellung heute zwischen 10 und 14 Uhr"
    )
    assert (
        hass.states.get(f"{prefix}_estimated_delivery").attributes["remark"]
        == "Zustellung heute zwischen 10 und 14 Uhr"
    )


async def test_pickup_day_and_pickup_time(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The pickup field gets the same treatment as the delivery forecast."""
    payload = shipment_payload(TRACKING_NUMBER)
    payload["pickUpDate"] = "2026-09-19"
    shipment_responses[TRACKING_NUMBER] = payload
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    prefix = f"sensor.dhl_{TRACKING_NUMBER.lower()}"
    assert hass.states.get(f"{prefix}_pickup_date").state == "unknown"
    assert hass.states.get(f"{prefix}_pickup_day").state == "2026-09-19"
