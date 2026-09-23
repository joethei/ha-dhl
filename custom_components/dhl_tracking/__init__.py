"""DHL Tracking integration for Home Assistant."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import DhlTrackingApi
from .const import CONF_API_KEY, DOMAIN
from .coordinator import DhlUpdateCoordinator
from .models import DhlOptions, migrate_legacy_options
from .services import async_register_services
from .store import DhlStateStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class DhlRuntimeData:
    """Runtime data stored on the config entry."""

    coordinator: DhlUpdateCoordinator
    store: DhlStateStore
    lock: asyncio.Lock


type DhlConfigEntry = ConfigEntry[DhlRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration level actions."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DhlConfigEntry) -> bool:
    """Set up DHL Tracking from a config entry."""
    options = DhlOptions.from_mapping(entry.options)

    api = DhlTrackingApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    store = DhlStateStore(hass, entry.entry_id)
    coordinator = DhlUpdateCoordinator(hass, entry, api, options, store)
    # Restores the cached payloads, so entities have data straight away and a
    # restart does not force a fresh API call for every shipment.
    await coordinator.async_initialize()

    entry.runtime_data = DhlRuntimeData(
        coordinator=coordinator, store=store, lock=asyncio.Lock()
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))

    # Refreshing in the background keeps setup fast: with the mandatory
    # ~6 seconds between DHL API calls, polling many shipments synchronously
    # would stall the config entry setup.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN} initial refresh"
    )
    return True


async def async_options_updated(hass: HomeAssistant, entry: DhlConfigEntry) -> None:
    """Apply changed options without reloading the config entry.

    Both the actions (``dhl_tracking.add_shipment`` and friends) and the
    options flow persist their changes in the config entry options, so this
    single listener is the only place that has to react to them.
    """
    if (runtime := getattr(entry, "runtime_data", None)) is None:
        return
    await runtime.coordinator.async_apply_options(
        DhlOptions.from_mapping(entry.options)
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry to the current schema."""
    _LOGGER.debug(
        "Migrating DHL Tracking config entry from version %s.%s",
        entry.version,
        entry.minor_version,
    )

    if entry.version > 2:
        # Downgrading from a future schema version is not supported.
        return False

    if entry.version == 1:
        # Version 1 kept the API key *and* the tracking numbers in
        # `entry.data`, where `tracking_numbers` was either a list (created by
        # the config flow) or the raw comma separated string the user typed.
        shipments = migrate_legacy_options(entry.data)
        if not shipments:
            shipments = migrate_legacy_options(entry.options)

        new_options = DhlOptions.from_mapping(
            {**entry.options, "shipments": shipments}
        ).as_dict()

        hass.config_entries.async_update_entry(
            entry,
            data={CONF_API_KEY: entry.data[CONF_API_KEY]},
            options=new_options,
            version=2,
            minor_version=1,
        )
        _LOGGER.info(
            "Migrated DHL Tracking config entry to version 2 (%s shipment(s))",
            len(shipments),
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DhlConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and (runtime := getattr(entry, "runtime_data", None)) is not None:
        await runtime.coordinator.async_shutdown()
        await runtime.store.async_save_now()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the persisted runtime state when the entry is removed."""
    await DhlStateStore(hass, entry.entry_id).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DhlConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a shipment by deleting its device in the UI."""
    identifiers = {
        identifier[1] for identifier in device.identifiers if identifier[0] == DOMAIN
    }
    # The per-entry service device carries the entry id and may always go.
    if entry.entry_id in identifiers:
        return True

    options = DhlOptions.from_mapping(entry.options)
    remaining = [
        shipment
        for shipment in options.shipments
        if shipment.tracking_number not in identifiers
    ]
    if len(remaining) != len(options.shipments):
        hass.config_entries.async_update_entry(
            entry, options=options.with_shipments(remaining).as_dict()
        )
    return True
