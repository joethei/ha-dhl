"""Persistent runtime state for the DHL Tracking integration.

The *user configuration* (API key, tracked shipments, poll interval) lives in
the config entry - see ``models.DhlOptions``. This module stores the
*runtime bookkeeping* that must survive a restart but is not user editable:

* when each shipment was last polled, so a Home Assistant restart cannot
  bypass the daily DHL request budget,
* how many requests were already spent today,
* the last known status per shipment, so the ``dhl_tracking_status_changed``
  event is not re-fired for unchanged shipments after a restart,
* the last API payload, so entities are populated immediately after a restart
  without spending another API call.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

STORAGE_VERSION = 1
STORAGE_KEY_TEMPLATE = "dhl_tracking.{}"
SAVE_DELAY = 10


class DhlStateStore:
    """Thin typed wrapper around a Home Assistant ``Store``."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store."""
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id)
        )
        self._data: dict[str, Any] = {"budget": {}, "shipments": {}}

    async def async_load(self) -> dict[str, Any]:
        """Load the stored state."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._data = {
                "budget": stored.get("budget") or {},
                "shipments": stored.get("shipments") or {},
            }
        return self._data

    @property
    def data(self) -> dict[str, Any]:
        """Return the in-memory state."""
        return self._data

    def async_set(self, data: dict[str, Any]) -> None:
        """Replace the in-memory state and schedule a debounced save."""
        self._data = data
        self._store.async_delay_save(lambda: self._data, SAVE_DELAY)

    async def async_save_now(self) -> None:
        """Flush pending state to disk immediately."""
        await self._store.async_save(self._data)

    async def async_remove(self) -> None:
        """Delete the stored state (config entry removal)."""
        await self._store.async_remove()
