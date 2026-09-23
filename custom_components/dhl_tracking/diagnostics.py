"""Diagnostics support for the DHL Tracking integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_API_KEY, CONF_RECIPIENT_POSTAL_CODE
from .coordinator import PRIORITY_WEIGHTS

# The API key is a credential; the remaining keys carry the recipient's
# personal data (names, street addresses, signatures) which is never needed to
# debug the integration.
TO_REDACT = {
    CONF_API_KEY,
    CONF_RECIPIENT_POSTAL_CODE,
    "carrier",
    "consignee",
    "postalCode",
    "proofOfDelivery",
    "receiver",
    "recipientPostalCode",
    "sender",
    "shipper",
    "signed",
    "streetAddress",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator

    return async_redact_data(
        {
            "entry": {
                "version": entry.version,
                "minor_version": entry.minor_version,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "budget": coordinator.budget.as_dict(),
            "scheduling": {
                "scan_interval": coordinator.options.scan_interval,
                "poll_delivered": coordinator.options.poll_delivered,
                "priority_counts": coordinator.priority_counts(),
                "fair_share_interval_seconds": {
                    priority.value: coordinator.fair_share_interval(
                        priority
                    ).total_seconds()
                    for priority in PRIORITY_WEIGHTS
                },
                "priority_floor_seconds": {
                    priority.value: coordinator.priority_floor(priority).total_seconds()
                    for priority in PRIORITY_WEIGHTS
                },
                "estimated_requests_per_day": coordinator.estimated_daily_requests(),
            },
            "shipments": [
                {
                    "tracking_number": state.tracking_number,
                    "name": state.shipment.name,
                    "created_at": state.shipment.created_at,
                    "last_polled": (
                        state.last_polled.isoformat() if state.last_polled else None
                    ),
                    "last_success": (
                        state.last_success.isoformat() if state.last_success else None
                    ),
                    "error": state.error,
                    "status": state.status,
                    "status_code": state.status_code,
                    "priority": state.priority(dt_util.utcnow()).value,
                    "data": state.data,
                }
                for state in coordinator.states.values()
            ],
        },
        TO_REDACT,
    )
