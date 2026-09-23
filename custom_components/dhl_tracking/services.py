"""Actions (services) of the DHL Tracking integration.

The actions and the options flow write to the very same place - the config
entry options - so both stay in sync automatically.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_OLDER_THAN_DAYS,
    CONF_NAME,
    CONF_RECIPIENT_POSTAL_CODE,
    CONF_TRACKING_NUMBER,
    DEFAULT_OLDER_THAN_DAYS,
    DOMAIN,
    SERVICE_ADD_SHIPMENT,
    SERVICE_REMOVE_DELIVERED_SHIPMENTS,
    SERVICE_REMOVE_SHIPMENT,
)
from .models import DhlOptions, Shipment, normalize_tracking_number

_LOGGER = logging.getLogger(__name__)

ADD_SHIPMENT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRACKING_NUMBER): vol.Any(cv.string, int),
        vol.Optional(CONF_NAME): vol.Any(cv.string, None),
        vol.Optional(CONF_RECIPIENT_POSTAL_CODE): vol.Any(cv.string, int, None),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

REMOVE_SHIPMENT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRACKING_NUMBER): vol.Any(cv.string, int),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

REMOVE_DELIVERED_SHIPMENTS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_OLDER_THAN_DAYS, default=DEFAULT_OLDER_THAN_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=365)
        ),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration actions once per Home Assistant start."""
    if hass.services.has_service(DOMAIN, SERVICE_ADD_SHIPMENT):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        _async_add_shipment,
        schema=ADD_SHIPMENT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_SHIPMENT,
        _async_remove_shipment,
        schema=REMOVE_SHIPMENT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_DELIVERED_SHIPMENTS,
        _async_remove_delivered_shipments,
        schema=REMOVE_DELIVERED_SHIPMENTS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _async_resolve_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry:
    """Return the config entry the action should operate on."""
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]

    if entry_id is not None:
        for entry in loaded:
            if entry.entry_id == entry_id:
                return entry
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_config_entry",
            translation_placeholders={"config_entry_id": entry_id},
        )

    if not loaded:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_config_entry"
        )
    if len(loaded) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="multiple_config_entries"
        )
    return loaded[0]


async def _async_write_shipments(
    hass: HomeAssistant, entry: ConfigEntry, options: DhlOptions
) -> None:
    """Persist the shipment list and apply it to the running coordinator."""
    hass.config_entries.async_update_entry(entry, options=options.as_dict())
    # `async_update_entry` notifies the update listener in a background task.
    # Applying the change here as well makes the action deterministic: when it
    # returns, the entities exist (or are gone). The listener then finds an
    # empty diff and does nothing.
    await entry.runtime_data.coordinator.async_apply_options(options)


async def _async_add_shipment(call: ServiceCall) -> None:
    """Handle the ``dhl_tracking.add_shipment`` action."""
    hass = call.hass
    entry = _async_resolve_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))

    shipment = Shipment.create(
        str(call.data[CONF_TRACKING_NUMBER]),
        call.data.get(CONF_NAME),
        _optional_str(call.data.get(CONF_RECIPIENT_POSTAL_CODE)),
    )

    async with entry.runtime_data.lock:
        options = DhlOptions.from_mapping(entry.options)
        if options.get(shipment.tracking_number) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="already_tracked",
                translation_placeholders={"tracking_number": shipment.tracking_number},
            )
        await _async_write_shipments(
            hass, entry, options.with_shipments([*options.shipments, shipment])
        )

    _LOGGER.debug("Added shipment %s", shipment.tracking_number)


async def _async_remove_shipment(call: ServiceCall) -> None:
    """Handle the ``dhl_tracking.remove_shipment`` action."""
    hass = call.hass
    entry = _async_resolve_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
    tracking_number = normalize_tracking_number(str(call.data[CONF_TRACKING_NUMBER]))

    async with entry.runtime_data.lock:
        options = DhlOptions.from_mapping(entry.options)
        if options.get(tracking_number) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_tracked",
                translation_placeholders={"tracking_number": tracking_number},
            )
        await _async_write_shipments(
            hass,
            entry,
            options.with_shipments(
                shipment
                for shipment in options.shipments
                if shipment.tracking_number != tracking_number
            ),
        )

    _LOGGER.debug("Removed shipment %s", tracking_number)


async def _async_remove_delivered_shipments(call: ServiceCall) -> ServiceResponse:
    """Handle the ``dhl_tracking.remove_delivered_shipments`` action."""
    hass = call.hass
    entry = _async_resolve_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
    older_than_days: int = call.data[ATTR_OLDER_THAN_DAYS]
    cutoff = dt_util.utcnow() - timedelta(days=older_than_days)

    removed = await async_purge_delivered(hass, entry, cutoff)
    return {"removed": removed, "count": len(removed)}


async def async_purge_delivered(
    hass: HomeAssistant, entry: ConfigEntry, cutoff: datetime
) -> list[str]:
    """Remove every shipment delivered at or before ``cutoff``.

    Shared by the action and by the automatic cleanup in the coordinator, so
    both behave identically.
    """
    async with entry.runtime_data.lock:
        coordinator = entry.runtime_data.coordinator
        options = DhlOptions.from_mapping(entry.options)

        removed: list[str] = []
        for shipment in options.shipments:
            state = coordinator.states.get(shipment.tracking_number)
            if state is None or not state.delivered:
                continue
            delivered_at = state.delivered_at
            if delivered_at is None:
                _LOGGER.debug(
                    "Shipment %s is delivered but has no delivery timestamp; keeping it",
                    shipment.tracking_number,
                )
                continue
            if delivered_at <= cutoff:
                removed.append(shipment.tracking_number)

        if removed:
            await _async_write_shipments(
                hass,
                entry,
                options.with_shipments(
                    shipment
                    for shipment in options.shipments
                    if shipment.tracking_number not in removed
                ),
            )

    return removed


def _optional_str(value: Any) -> str | None:
    """Return ``value`` as a string, preserving ``None``."""
    return None if value is None else str(value)
