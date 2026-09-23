"""Tests for references, the extra status texts and the reroute link."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from homeassistant.const import MAX_LENGTH_STATE_STATE
from homeassistant.core import HomeAssistant

from .conftest import build_config_entry, setup_integration
from .const import TRACKING_NUMBER, shipment_payload

PREFIX = f"sensor.dhl_{TRACKING_NUMBER.lower()}"


async def setup_with(hass: HomeAssistant, responses: dict, **changes) -> None:
    """Set up one shipment whose payload is patched with ``changes``."""
    data = shipment_payload(TRACKING_NUMBER)
    for key, value in changes.items():
        if key == "status":
            data["status"].update(value)
        elif key == "references":
            data["details"]["references"] = value
        else:
            data[key] = value
    responses[TRACKING_NUMBER] = data
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)


# --- references ----------------------------------------------------------------


async def test_customer_reference_prefers_the_order_number(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The order number wins over the other reference types."""
    await setup_with(
        hass,
        shipment_responses,
        references=[
            {"type": "housebill", "number": "HB-1"},
            {"type": "customer-reference", "number": "CR-2"},
            {"type": "customer-order-number", "number": "ORDER-4711"},
        ],
    )

    state = hass.states.get(f"{PREFIX}_customer_reference")
    assert state.state == "ORDER-4711"
    assert state.attributes["references"] == [
        {"type": "housebill", "number": "HB-1"},
        {"type": "customer-reference", "number": "CR-2"},
        {"type": "customer-order-number", "number": "ORDER-4711"},
    ]
    # Also reachable from the dashboard's anchor sensor.
    assert (
        hass.states.get(f"{PREFIX}_status_code").attributes["customer_reference"]
        == "ORDER-4711"
    )


async def test_customer_reference_falls_back_to_the_first_entry(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """An unranked type is still better than nothing."""
    await setup_with(
        hass,
        shipment_responses,
        references=[{"type": "routing-code", "number": "RC-9"}],
    )
    assert hass.states.get(f"{PREFIX}_customer_reference").state == "RC-9"


@pytest.mark.parametrize(
    "reference",
    [
        {"type": "payer-account-number", "number": "ACCT-PAYER"},
        {"type": "shipper-account-number", "number": "ACCT-SHIPPER"},
        {"type": "receiver-account-number", "number": "ACCT-RECEIVER"},
        {"type": "customer-reference", "number": "geheim", "@scope": "secret"},
        {"type": "customer-reference", "number": "geheim", "@scope": "sensitive"},
    ],
)
async def test_protected_references_are_dropped(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    shipment_responses: dict,
    reference: dict,
) -> None:
    """Account numbers and anything DHL scopes as protected stay private."""
    await setup_with(hass, shipment_responses, references=[reference])

    state = hass.states.get(f"{PREFIX}_customer_reference")
    assert state.state == "unknown"
    assert state.attributes["references"] == []
    assert "ACCT-" not in str(state.attributes)
    assert "geheim" not in str(state.attributes)


async def test_public_scope_is_kept(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """An explicitly public reference is published."""
    await setup_with(
        hass,
        shipment_responses,
        references=[
            {"type": "customer-order-number", "number": "ORDER-1", "@scope": "public"}
        ],
    )
    assert hass.states.get(f"{PREFIX}_customer_reference").state == "ORDER-1"


@pytest.mark.parametrize(
    "references",
    [[], [{"type": "customer-reference"}], [{"number": "no-type"}], ["nonsense"], None],
)
async def test_broken_references_are_ignored(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict, references
) -> None:
    """Incomplete entries never reach the state machine."""
    await setup_with(hass, shipment_responses, references=references)
    assert hass.states.get(f"{PREFIX}_customer_reference").state == "unknown"


# --- extra status texts --------------------------------------------------------


async def test_next_steps_sensor(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """nextSteps gets its own sensor and shows up in the summary."""
    await setup_with(
        hass,
        shipment_responses,
        status={"nextSteps": "Bitte halten Sie Ihren Ausweis bereit."},
    )
    assert (
        hass.states.get(f"{PREFIX}_next_steps").state
        == "Bitte halten Sie Ihren Ausweis bereit."
    )
    assert (
        hass.states.get(f"{PREFIX}_status_code").attributes["next_steps"]
        == "Bitte halten Sie Ihren Ausweis bereit."
    )


async def test_status_detailed_and_remark_attributes(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The remaining status texts ride along as attributes."""
    await setup_with(
        hass,
        shipment_responses,
        status={
            "statusDetailed": "Auf dem Weg zur Zustellbasis",
            "remark": "Empfänger nicht angetroffen",
        },
    )

    for entity_id in (f"{PREFIX}_status_description", f"{PREFIX}_status_code"):
        attrs = hass.states.get(entity_id).attributes
        assert attrs["status_detailed"] == "Auf dem Weg zur Zustellbasis"
        assert attrs["status_remark"] == "Empfänger nicht angetroffen"


async def test_missing_status_texts_add_no_attributes(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Absent fields do not create empty attributes."""
    await setup_with(hass, shipment_responses)
    attrs = hass.states.get(f"{PREFIX}_status_code").attributes
    assert "status_detailed" not in attrs
    assert "status_remark" not in attrs
    assert "next_steps" not in attrs


# --- reroute --------------------------------------------------------------------


async def test_reroute_url(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The reroute link becomes a sensor and a summary attribute."""
    url = "https://www.dhl.de/reroute?piece=00340434123456789012"
    await setup_with(hass, shipment_responses, rerouteUrl=url)

    assert hass.states.get(f"{PREFIX}_reroute_url").state == url
    attrs = hass.states.get(f"{PREFIX}_status_code").attributes
    assert attrs["reroute_url"] == url
    assert attrs["reroute_available"] is True


async def test_reroute_absent_means_not_available(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """DHL only sends the link while rerouting is possible."""
    await setup_with(hass, shipment_responses)

    assert hass.states.get(f"{PREFIX}_reroute_url").state == "unknown"
    attrs = hass.states.get(f"{PREFIX}_status_code").attributes
    assert attrs["reroute_available"] is False
    assert "reroute_url" not in attrs


# --- long free text --------------------------------------------------------------


async def test_long_text_is_truncated_not_dropped(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Home Assistant refuses states over 255 characters outright."""
    long_text = "Sehr ausfuehrliche Statusbeschreibung. " * 20
    assert len(long_text) > MAX_LENGTH_STATE_STATE
    await setup_with(hass, shipment_responses, status={"description": long_text})

    state = hass.states.get(f"{PREFIX}_status_description")
    assert state is not None, "the entity must not break on a long value"
    assert len(state.state) <= MAX_LENGTH_STATE_STATE
    assert state.state.endswith("…")
    # Nothing is lost.
    assert state.attributes["full_value"] == long_text


async def test_short_text_gets_no_full_value(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The extra attribute only appears when it is actually needed."""
    await setup_with(hass, shipment_responses)
    attrs = hass.states.get(f"{PREFIX}_status_description").attributes
    assert "full_value" not in attrs
