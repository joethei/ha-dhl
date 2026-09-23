"""Diagnostics redaction tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dhl_tracking.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant

from .conftest import setup_integration
from .const import API_KEY


async def test_diagnostics_redact_credentials_and_personal_data(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Neither the API key nor recipient details end up in diagnostics."""
    await setup_integration(hass, mock_config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    dumped = json.dumps(diagnostics)

    assert API_KEY not in dumped
    assert "Erika Mustermann" not in dumped
    assert "40667" not in dumped
    assert diagnostics["entry"]["data"]["api_key"] == "**REDACTED**"

    # The parts that are actually useful for debugging survive.
    assert diagnostics["shipments"][0]["status_code"] == "transit"
    assert diagnostics["budget"]["count"] == 1
    assert diagnostics["scheduling"]["active_shipments"] == 1
