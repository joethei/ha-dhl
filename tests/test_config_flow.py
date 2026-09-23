"""Config flow and options flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dhl_tracking.api import (
    DhlAuthError,
    DhlConnectionError,
    DhlRateLimitError,
)
from custom_components.dhl_tracking.const import (
    CONF_API_KEY,
    CONF_AUTO_REMOVE_DELIVERED_DAYS,
    CONF_LANGUAGE,
    CONF_POLL_DELIVERED,
    CONF_SCAN_INTERVAL,
    CONF_TRACKING_NUMBERS,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from custom_components.dhl_tracking.models import DhlOptions
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er

from .conftest import build_config_entry, setup_integration
from .const import API_KEY, OTHER_TRACKING_NUMBER, TRACKING_NUMBER

VALIDATE = (
    "custom_components.dhl_tracking.api.DhlTrackingApi.async_validate_credentials"
)


async def test_user_flow_without_tracking_numbers(hass: HomeAssistant) -> None:
    """The initial setup works with only an API key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with (
        patch(VALIDATE, return_value=None),
        patch(
            "custom_components.dhl_tracking.async_setup_entry", return_value=True
        ) as setup_mock,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: f"  {API_KEY}  "}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: API_KEY}
    assert result["options"]["shipments"] == []
    assert result["options"][CONF_SCAN_INTERVAL] >= MIN_SCAN_INTERVAL
    assert len(setup_mock.mock_calls) == 1


async def test_user_flow_with_tracking_numbers(hass: HomeAssistant) -> None:
    """Comma separated numbers from the setup form are stored as shipments."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with (
        patch(VALIDATE, return_value=None),
        patch("custom_components.dhl_tracking.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_API_KEY: API_KEY,
                CONF_TRACKING_NUMBERS: (
                    f"{TRACKING_NUMBER}, {OTHER_TRACKING_NUMBER},, {TRACKING_NUMBER}"
                ),
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    numbers = [s["tracking_number"] for s in result["options"]["shipments"]]
    assert numbers == [TRACKING_NUMBER, OTHER_TRACKING_NUMBER]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DhlAuthError(), "invalid_auth"),
        (DhlConnectionError(), "cannot_connect"),
        (DhlRateLimitError(), "rate_limited"),
    ],
)
async def test_user_flow_api_errors(
    hass: HomeAssistant, error: Exception, expected: str
) -> None:
    """API failures are surfaced as recoverable form errors."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, side_effect=error):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    # Recovery in the same flow must work.
    with (
        patch(VALIDATE, return_value=None),
        patch("custom_components.dhl_tracking.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_tracking_number(hass: HomeAssistant) -> None:
    """An invalid number is reported on the tracking numbers field."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: API_KEY, CONF_TRACKING_NUMBERS: "12"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TRACKING_NUMBERS: "invalid_tracking_number"}


async def test_user_flow_duplicate_api_key(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """The same API key cannot be configured twice."""
    entry = build_config_entry(shipments=[])
    await setup_integration(hass, entry)
    # Match the fingerprint the flow will compute for API_KEY.
    hass.config_entries.async_update_entry(
        entry,
        unique_id=__import__("hashlib").sha256(API_KEY.encode()).hexdigest()[:16],
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Re-authentication replaces the stored API key."""
    await setup_integration(hass, mock_config_entry)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(VALIDATE, side_effect=DhlAuthError()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "wrong"}
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch(VALIDATE, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_API_KEY] == "new-key"


async def test_options_flow_add_and_remove(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The options flow adds and removes shipments through the same storage."""
    await setup_integration(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {
        "add_shipment",
        "edit_shipment",
        "remove_shipment",
        "settings",
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_shipment"}
    )
    assert result["step_id"] == "add_shipment"

    # A duplicate is rejected on the tracking number field.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_number": TRACKING_NUMBER}
    )
    assert result["errors"] == {"tracking_number": "already_tracked"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Zweites Paket"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    options = DhlOptions.from_mapping(mock_config_entry.options)
    assert [s.tracking_number for s in options.shipments] == [
        TRACKING_NUMBER,
        OTHER_TRACKING_NUMBER,
    ]
    assert hass.states.get("sensor.zweites_paket_status") is not None

    # Remove it again.
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_shipment"}
    )
    assert result["step_id"] == "remove_shipment"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"selected": [OTHER_TRACKING_NUMBER]}
    )
    await hass.async_block_till_done()

    assert [
        s.tracking_number
        for s in DhlOptions.from_mapping(mock_config_entry.options).shipments
    ] == [TRACKING_NUMBER]
    assert hass.states.get("sensor.zweites_paket_status") is None


async def test_options_flow_rename_keeps_unique_ids(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Renaming a shipment must not recreate its entities."""
    await setup_integration(hass, mock_config_entry)
    entity_registry = er.async_get(hass)
    before = {
        entity.entity_id: entity.unique_id
        for entity in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
    }

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_shipment"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"selected": TRACKING_NUMBER}
    )
    assert result["step_id"] == "edit_details"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Neuer Name", "recipient_postal_code": "54321"}
    )
    await hass.async_block_till_done()

    after = {
        entity.entity_id: entity.unique_id
        for entity in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
    }
    assert after == before

    updated = DhlOptions.from_mapping(mock_config_entry.options).get(TRACKING_NUMBER)
    assert updated is not None
    assert updated.name == "Neuer Name"
    assert updated.recipient_postal_code == "54321"
    # The created_at timestamp is preserved across a rename.
    assert updated.created_at == "2026-09-01T10:00:00+00:00"


async def test_options_flow_settings(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The scan interval is configurable but clamped to safe values."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    # The selector already refuses anything below the 5 minute floor.
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_SCAN_INTERVAL: 1, CONF_LANGUAGE: "en", CONF_POLL_DELIVERED: False},
        )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 5, CONF_LANGUAGE: "en", CONF_POLL_DELIVERED: False},
    )
    await hass.async_block_till_done()

    options = DhlOptions.from_mapping(mock_config_entry.options)
    assert options.scan_interval == MIN_SCAN_INTERVAL
    assert options.language == "en"
    assert options.poll_delivered is False
    assert coordinator.options.language == "en"
    assert coordinator.update_interval.total_seconds() == MIN_SCAN_INTERVAL


async def test_options_menu_without_shipments(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """Edit/remove are hidden when nothing is tracked."""
    entry = build_config_entry(shipments=[])
    await setup_integration(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == ["add_shipment", "settings"]


async def test_options_flow_auto_remove_delivered(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The automatic cleanup interval is configurable from the UI."""
    await setup_integration(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 30,
            CONF_LANGUAGE: "de",
            CONF_POLL_DELIVERED: True,
            CONF_AUTO_REMOVE_DELIVERED_DAYS: 7,
        },
    )
    await hass.async_block_till_done()

    options = DhlOptions.from_mapping(mock_config_entry.options)
    assert options.auto_remove_delivered_days == 7
    assert (
        mock_config_entry.runtime_data.coordinator.options.auto_remove_delivered_days
        == 7
    )


async def test_options_flow_auto_remove_defaults(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Submitting the settings step without the field keeps a valid value."""
    await setup_integration(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 30, CONF_LANGUAGE: "de", CONF_POLL_DELIVERED: True},
    )
    await hass.async_block_till_done()

    options = DhlOptions.from_mapping(mock_config_entry.options)
    assert options.auto_remove_delivered_days == 0
