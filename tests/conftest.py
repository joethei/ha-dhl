"""Fixtures for the DHL Tracking tests.

None of the tests talk to the real DHL API: every fixture either patches the
API client or serves canned responses through Home Assistant's aiohttp mocker.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dhl_tracking.const import (
    CONF_API_KEY,
    CONF_AUTO_REMOVE_DELIVERED_DAYS,
    CONF_SHIPMENTS,
    DOMAIN,
)
from homeassistant.core import HomeAssistant

from .const import API_KEY, TRACKING_NUMBER, shipment_payload

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> Generator[None]:
    """Enable loading the integration from custom_components/."""
    yield


@pytest.fixture(autouse=True)
def no_api_throttle() -> Generator[None]:
    """Remove the 6 second spacing between API calls so tests run fast."""
    with patch(
        "custom_components.dhl_tracking.coordinator.API_MIN_SECONDS_BETWEEN_CALLS", 0
    ):
        yield


@pytest.fixture
def shipment_responses() -> dict[str, Any]:
    """Return the mutable tracking-number -> payload mapping used by mock_api."""
    return {TRACKING_NUMBER: shipment_payload(TRACKING_NUMBER)}


@pytest.fixture
def mock_api(shipment_responses: dict[str, Any]) -> Generator[AsyncMock]:
    """Patch the DHL API client.

    ``shipment_responses`` maps a tracking number to either a payload dict, an
    exception instance (which is raised) or ``None`` (no shipment found).
    Unknown numbers resolve to a generic payload.
    """

    async def _get_shipment(tracking_number: str, **kwargs: Any) -> Any:
        result = shipment_responses.get(tracking_number, ...)
        if result is ...:
            return shipment_payload(tracking_number)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return result(tracking_number, **kwargs)
        return result

    with (
        patch(
            "custom_components.dhl_tracking.api.DhlTrackingApi.async_get_shipment",
            side_effect=_get_shipment,
            autospec=False,
        ) as mocked,
        patch(
            "custom_components.dhl_tracking.api.DhlTrackingApi.async_validate_credentials",
            return_value=None,
        ),
    ):
        yield mocked


def build_config_entry(
    *,
    shipments: list[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    version: int = 2,
    minor_version: int = 1,
    unique_id: str = "dhl-test-fingerprint",
) -> MockConfigEntry:
    """Create a MockConfigEntry for the integration."""
    if options is None:
        entry_options: dict[str, Any] = {CONF_SHIPMENTS: shipments or []}
    else:
        entry_options = dict(options)
        if shipments is not None:
            entry_options[CONF_SHIPMENTS] = shipments
    # Automatic cleanup of delivered shipments is opt-in per test, so that a
    # fixture timestamp drifting past the default age cannot silently delete
    # shipments a test is asserting on.
    entry_options.setdefault(CONF_AUTO_REMOVE_DELIVERED_DAYS, 0)
    return MockConfigEntry(
        domain=DOMAIN,
        title="DHL Tracking",
        data=data if data is not None else {CONF_API_KEY: API_KEY},
        options=entry_options,
        version=version,
        minor_version=minor_version,
        unique_id=unique_id,
    )


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry with a single tracked shipment."""
    return build_config_entry(
        shipments=[
            {
                "tracking_number": TRACKING_NUMBER,
                "name": "Testpaket",
                "recipient_postal_code": "40667",
                "created_at": "2026-09-01T10:00:00+00:00",
            }
        ]
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def setup_entry() -> Callable[[HomeAssistant, MockConfigEntry], Any]:
    """Expose the setup helper as a fixture."""
    return setup_integration
