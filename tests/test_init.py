"""Setup, migration and persistence tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dhl_tracking.const import (
    CONF_API_KEY,
    CONF_SHIPMENTS,
    CONF_TRACKING_NUMBERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_ADD_SHIPMENT,
    SERVICE_REMOVE_DELIVERED_SHIPMENTS,
    SERVICE_REMOVE_SHIPMENT,
)
from custom_components.dhl_tracking.models import DhlOptions
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import build_config_entry, setup_integration
from .const import API_KEY, OTHER_TRACKING_NUMBER, TRACKING_NUMBER


async def test_setup_without_tracking_numbers(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """A fresh install without any shipment sets up cleanly."""
    entry = build_config_entry(shipments=[])
    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.coordinator.states == {}
    # No shipment means no API call at all.
    assert mock_api.call_count == 0

    # The actions are registered even without shipments.
    for service in (
        SERVICE_ADD_SHIPMENT,
        SERVICE_REMOVE_SHIPMENT,
        SERVICE_REMOVE_DELIVERED_SHIPMENTS,
    ):
        assert hass.services.has_service(DOMAIN, service)

    # Only the per-entry summary sensors exist, no shipment entities.
    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {entity.unique_id for entity in entities} == {
        f"{DOMAIN}_{entry.entry_id}_api_requests_today",
        f"{DOMAIN}_{entry.entry_id}_open_shipments",
        f"{DOMAIN}_{entry.entry_id}_next_delivery",
    }


async def test_setup_creates_entities(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Setting up an entry with a shipment creates its entities and device."""
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    state = hass.states.get("sensor.testpaket_status")
    assert state is not None
    assert state.state == "In transit"
    assert state.attributes["tracking_number"] == TRACKING_NUMBER


@pytest.mark.parametrize(
    ("legacy_value", "expected"),
    [
        (
            [TRACKING_NUMBER, OTHER_TRACKING_NUMBER],
            [TRACKING_NUMBER, OTHER_TRACKING_NUMBER],
        ),
        (
            f"{TRACKING_NUMBER},{OTHER_TRACKING_NUMBER}",
            [TRACKING_NUMBER, OTHER_TRACKING_NUMBER],
        ),
        (
            f" {TRACKING_NUMBER} , {OTHER_TRACKING_NUMBER} ",
            [TRACKING_NUMBER, OTHER_TRACKING_NUMBER],
        ),
        (TRACKING_NUMBER, [TRACKING_NUMBER]),
        ("", []),
        # Individual digits must not become separate tracking numbers.
        ("1,2,3", []),
    ],
    ids=["list", "csv", "csv-whitespace", "single-string", "empty", "digits"],
)
async def test_migration_from_version_1(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    legacy_value: object,
    expected: list[str],
) -> None:
    """Version 1 entries keep their tracking numbers after the migration."""
    entry = build_config_entry(
        data={CONF_API_KEY: API_KEY, CONF_TRACKING_NUMBERS: legacy_value},
        options={},
        version=1,
        minor_version=1,
    )
    await setup_integration(hass, entry)

    assert entry.version == 2
    assert entry.data == {CONF_API_KEY: API_KEY}
    assert CONF_TRACKING_NUMBERS not in entry.data

    options = DhlOptions.from_mapping(entry.options)
    assert [s.tracking_number for s in options.shipments] == expected
    assert all(s.created_at for s in options.shipments)
    assert options.scan_interval == DEFAULT_SCAN_INTERVAL


async def test_migration_keeps_entity_unique_ids(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """Entities registered by the old version are reused, not duplicated."""
    entry = build_config_entry(
        data={CONF_API_KEY: API_KEY, CONF_TRACKING_NUMBERS: [TRACKING_NUMBER]},
        version=1,
    )
    entry.add_to_hass(hass)

    entity_registry = er.async_get(hass)
    legacy = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_{TRACKING_NUMBER}_status",
        suggested_object_id=f"dhl_{TRACKING_NUMBER}_status",
        config_entry=entry,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    reused = entity_registry.async_get(legacy.entity_id)
    assert reused is not None
    assert hass.states.get(legacy.entity_id) is not None
    # No second entity was created for the same unique id.
    status_entities = [
        entity
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if entity.unique_id == f"{DOMAIN}_{TRACKING_NUMBER}_status"
    ]
    assert len(status_entities) == 1


async def test_shipments_survive_a_reload(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Shipments are persisted in the config entry and survive a reload."""
    await setup_integration(hass, mock_config_entry)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Zweites Paket"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    options = DhlOptions.from_mapping(mock_config_entry.options)
    assert [s.tracking_number for s in options.shipments] == [
        TRACKING_NUMBER,
        OTHER_TRACKING_NUMBER,
    ]
    assert mock_config_entry.runtime_data.coordinator.states.keys() == {
        TRACKING_NUMBER,
        OTHER_TRACKING_NUMBER,
    }


async def test_no_duplicate_entities_after_multiple_reloads(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Reloading repeatedly must not multiply entities."""
    await setup_integration(hass, mock_config_entry)
    entity_registry = er.async_get(hass)
    baseline = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
    }
    assert baseline

    for _ in range(3):
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    entities = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    assert len(entities) == len(baseline)
    assert {entity.unique_id for entity in entities} == baseline


async def test_unload_entry(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The entry unloads cleanly."""
    await setup_integration(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_migration_from_future_version_fails(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """A downgrade from an unknown schema version is refused."""
    entry = build_config_entry(version=3)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_shipments_are_stored_in_options_not_data(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Persistence uses the config entry options; data only holds the key."""
    await setup_integration(hass, mock_config_entry)
    assert set(mock_config_entry.data) == {CONF_API_KEY}
    assert CONF_SHIPMENTS in mock_config_entry.options
