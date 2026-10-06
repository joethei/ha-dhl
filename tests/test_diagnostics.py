"""Diagnostics redaction tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dhl_tracking.const import DOMAIN, SERVICE_REMOVE_SHIPMENT
from custom_components.dhl_tracking.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant

from .conftest import build_config_entry, setup_integration
from .const import API_KEY, TRACKING_NUMBER, shipment_payload


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
    assert diagnostics["scheduling"]["priority_counts"]["transit"] == 1
    assert diagnostics["shipments"][0]["priority"] == "transit"


async def test_observed_status_codes_outlive_shipment_and_restart(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Undocumented codes are collected so new cases can be mapped later."""
    data = shipment_payload(TRACKING_NUMBER)
    data["events"] = [
        {
            "timestamp": "2026-10-06T14:30:00",
            "statusCode": "transit",
            "status": "PO",
            "statusDetailed": "ADVIS_PFLOC_DD",
            "description": "Für diese Sendung wurde ein Ablageort vorgemerkt.",
        },
        {
            "timestamp": "2026-10-06T08:38:00",
            "statusCode": "transit",
            "status": "PO",
            "statusDetailed": "SRTED_NRQRD_PO",
            "description": "Die Sendung wurde in das <b>Zustellfahrzeug</b> geladen.",
        },
    ]
    shipment_responses[TRACKING_NUMBER] = data
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    await hass.services.async_call(
        DOMAIN, SERVICE_REMOVE_SHIPMENT, {"tracking_number": TRACKING_NUMBER}, True
    )
    await entry.runtime_data.coordinator.store.async_save_now()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    codes = diagnostics["observed_status_codes"]
    assert list(codes) == ["ADVIS_PFLOC_DD", "SRTED_NRQRD_PO"]
    assert codes["SRTED_NRQRD_PO"] == {
        "status": "PO",
        "status_code": "transit",
        "description": "Die Sendung wurde in das Zustellfahrzeug geladen.",
        "first_seen": codes["SRTED_NRQRD_PO"]["first_seen"],
        "last_seen": codes["SRTED_NRQRD_PO"]["last_seen"],
    }
    assert codes["SRTED_NRQRD_PO"]["first_seen"].startswith("2026-10-06T08:38:00")
