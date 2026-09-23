"""Tests for the dhl_tracking actions."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.dhl_tracking.const import (
    DOMAIN,
    EVENT_SHIPMENT_ADDED,
    EVENT_SHIPMENT_REMOVED,
    SERVICE_ADD_SHIPMENT,
    SERVICE_REMOVE_DELIVERED_SHIPMENTS,
    SERVICE_REMOVE_SHIPMENT,
)
from custom_components.dhl_tracking.models import DhlOptions
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import OTHER_TRACKING_NUMBER, TRACKING_NUMBER, shipment_payload


def tracked(entry: MockConfigEntry) -> list[str]:
    """Return the tracking numbers persisted in the entry options."""
    return [
        shipment.tracking_number
        for shipment in DhlOptions.from_mapping(entry.options).shipments
    ]


async def test_add_shipment(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A valid tracking number is stored and gets entities without a restart."""
    await setup_integration(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_SHIPMENT_ADDED)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {
            "tracking_number": f"  {OTHER_TRACKING_NUMBER}  ",
            "name": "  Ersatzteil  ",
            "recipient_postal_code": " 12345 ",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert tracked(mock_config_entry) == [TRACKING_NUMBER, OTHER_TRACKING_NUMBER]
    added = DhlOptions.from_mapping(mock_config_entry.options).get(
        OTHER_TRACKING_NUMBER
    )
    assert added is not None
    assert added.name == "Ersatzteil"
    assert added.recipient_postal_code == "12345"
    assert added.created_at is not None

    assert hass.states.get("sensor.ersatzteil_status") is not None

    assert len(events) == 1
    assert events[0].data == {
        "tracking_number": OTHER_TRACKING_NUMBER,
        "name": "Ersatzteil",
    }


@pytest.mark.parametrize(
    ("tracking_number", "error_key"),
    [
        ("", "empty_tracking_number"),
        ("   ", "empty_tracking_number"),
        ("12", "invalid_tracking_number"),
        ("00340434/12345", "invalid_tracking_number"),
        ("A" * 40, "invalid_tracking_number"),
    ],
)
async def test_add_shipment_rejects_invalid_numbers(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    mock_config_entry: MockConfigEntry,
    tracking_number: str,
    error_key: str,
) -> None:
    """Empty or malformed numbers raise a translated ServiceValidationError."""
    await setup_integration(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_SHIPMENT,
            {"tracking_number": tracking_number},
            blocking=True,
        )

    assert err.value.translation_key == error_key
    assert err.value.translation_domain == DOMAIN
    assert tracked(mock_config_entry) == [TRACKING_NUMBER]


async def test_add_shipment_rejects_duplicates(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Adding a known number errors out and leaves the stored data untouched."""
    await setup_integration(hass, mock_config_entry)
    before = dict(mock_config_entry.options)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_SHIPMENT,
            {"tracking_number": TRACKING_NUMBER, "name": "Anderer Name"},
            blocking=True,
        )

    assert err.value.translation_key == "already_tracked"
    assert dict(mock_config_entry.options) == before


async def test_add_shipment_concurrently(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """Two concurrent adds of the same number create exactly one shipment."""
    entry = build_config_entry(shipments=[])
    await setup_integration(hass, entry)

    results = await asyncio.gather(
        *(
            hass.services.async_call(
                DOMAIN,
                SERVICE_ADD_SHIPMENT,
                {"tracking_number": TRACKING_NUMBER},
                blocking=True,
            )
            for _ in range(5)
        ),
        return_exceptions=True,
    )
    await hass.async_block_till_done()

    failures = [r for r in results if isinstance(r, ServiceValidationError)]
    assert len(failures) == 4
    assert all(f.translation_key == "already_tracked" for f in failures)
    assert tracked(entry) == [TRACKING_NUMBER]

    entity_registry = er.async_get(hass)
    status_entities = [
        entity
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if entity.unique_id == f"{DOMAIN}_{TRACKING_NUMBER}_status"
    ]
    assert len(status_entities) == 1


async def test_remove_shipment(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Removing a shipment drops its entities and its device."""
    await setup_integration(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_SHIPMENT_REMOVED)

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    assert hass.states.get("sensor.testpaket_status") is not None
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, TRACKING_NUMBER)})
        is not None
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REMOVE_SHIPMENT,
        {"tracking_number": TRACKING_NUMBER},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert tracked(mock_config_entry) == []
    assert hass.states.get("sensor.testpaket_status") is None
    assert entity_registry.async_get("sensor.testpaket_status") is None
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, TRACKING_NUMBER)})
        is None
    )
    assert len(events) == 1
    assert events[0].data["tracking_number"] == TRACKING_NUMBER


async def test_remove_unknown_shipment(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Removing an untracked number raises a clear error."""
    await setup_integration(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REMOVE_SHIPMENT,
            {"tracking_number": OTHER_TRACKING_NUMBER},
            blocking=True,
        )

    assert err.value.translation_key == "not_tracked"
    assert tracked(mock_config_entry) == [TRACKING_NUMBER]


async def test_add_remove_add_leaves_no_orphans(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Re-adding a removed number recreates exactly one set of entities."""
    await setup_integration(hass, mock_config_entry)
    entity_registry = er.async_get(hass)

    for _ in range(2):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REMOVE_SHIPMENT,
            {"tracking_number": TRACKING_NUMBER},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert not [
            entity
            for entity in er.async_entries_for_config_entry(
                entity_registry, mock_config_entry.entry_id
            )
            if TRACKING_NUMBER in entity.unique_id
        ]

        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_SHIPMENT,
            {"tracking_number": TRACKING_NUMBER, "name": "Testpaket"},
            blocking=True,
        )
        await hass.async_block_till_done()

    entities = [
        entity
        for entity in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
        if TRACKING_NUMBER in entity.unique_id
    ]
    assert len(entities) == len({entity.unique_id for entity in entities})
    assert hass.states.get("sensor.testpaket_status") is not None


async def test_remove_delivered_shipments(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Only shipments delivered long enough ago are removed."""
    old = (dt_util.utcnow() - timedelta(days=10)).isoformat()
    recent = (dt_util.utcnow() - timedelta(days=1)).isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered", timestamp=old
    )
    shipment_responses[OTHER_TRACKING_NUMBER] = shipment_payload(
        OTHER_TRACKING_NUMBER,
        status="Delivered",
        status_code="delivered",
        timestamp=recent,
    )

    entry = build_config_entry(
        shipments=[
            {"tracking_number": TRACKING_NUMBER},
            {"tracking_number": OTHER_TRACKING_NUMBER},
        ]
    )
    await setup_integration(hass, entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_REMOVE_DELIVERED_SHIPMENTS,
        {"older_than_days": 7},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()

    assert response == {"removed": [TRACKING_NUMBER], "count": 1}
    assert tracked(entry) == [OTHER_TRACKING_NUMBER]


async def test_remove_delivered_shipments_keeps_active(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Shipments that are still in transit are never removed."""
    await setup_integration(hass, mock_config_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_REMOVE_DELIVERED_SHIPMENTS,
        {"older_than_days": 0},
        blocking=True,
        return_response=True,
    )

    assert response == {"removed": [], "count": 0}
    assert tracked(mock_config_entry) == [TRACKING_NUMBER]


async def test_action_without_config_entry(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """Calling an action without a loaded entry raises a clear error."""
    assert await async_setup_domain(hass)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_SHIPMENT,
            {"tracking_number": TRACKING_NUMBER},
            blocking=True,
        )
    assert err.value.translation_key == "no_config_entry"


async def test_action_with_multiple_config_entries(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """With several entries the action requires an explicit config_entry_id."""
    first = build_config_entry(shipments=[], unique_id="fingerprint-1")
    second = build_config_entry(shipments=[], unique_id="fingerprint-2")
    await setup_integration(hass, first)
    await setup_integration(hass, second)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_SHIPMENT,
            {"tracking_number": TRACKING_NUMBER},
            blocking=True,
        )
    assert err.value.translation_key == "multiple_config_entries"

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {"tracking_number": TRACKING_NUMBER, "config_entry_id": second.entry_id},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert tracked(first) == []
    assert tracked(second) == [TRACKING_NUMBER]

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_SHIPMENT,
            {"tracking_number": TRACKING_NUMBER, "config_entry_id": "does-not-exist"},
            blocking=True,
        )
    assert err.value.translation_key == "invalid_config_entry"


async def async_setup_domain(hass: HomeAssistant) -> bool:
    """Load the component so its actions are registered without an entry."""
    from homeassistant.setup import async_setup_component

    return await async_setup_component(hass, DOMAIN, {})


async def test_removing_the_device_removes_the_shipment(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Deleting a shipment device in the UI untracks the shipment."""
    from custom_components.dhl_tracking import async_remove_config_entry_device

    await setup_integration(hass, mock_config_entry)
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, TRACKING_NUMBER)})
    assert device is not None

    assert await async_remove_config_entry_device(hass, mock_config_entry, device)
    await hass.async_block_till_done()

    assert tracked(mock_config_entry) == []
    assert hass.states.get("sensor.testpaket_status") is None
