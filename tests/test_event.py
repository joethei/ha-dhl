"""Tests for the per shipment event entity and the handover attributes."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.dhl_tracking.const import (
    DOMAIN,
    EVENT_STATUS_CHANGED,
    SERVICE_ADD_SHIPMENT,
    SERVICE_REMOVE_SHIPMENT,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import build_config_entry, setup_integration
from .const import OTHER_TRACKING_NUMBER, TRACKING_NUMBER, shipment_payload

EVENT_ENTITY = "event.testpaket_shipment_status"


async def test_event_entity_exists_per_shipment(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Every shipment gets one event entity with the documented event types."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(EVENT_ENTITY)
    assert state is not None
    assert set(state.attributes["event_types"]) == {
        "pre_transit",
        "transit",
        "out_for_delivery",
        "delivered",
        "failure",
        "unknown",
    }


async def test_no_event_on_startup(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Loading a known shipment must not replay a status event."""
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await setup_integration(hass, mock_config_entry)

    assert events == []
    # The entity exists but has never fired.
    assert hass.states.get(EVENT_ENTITY).state == "unknown"


async def test_event_fires_on_a_real_status_change(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    mock_config_entry: MockConfigEntry,
    shipment_responses: dict,
) -> None:
    """A genuine change triggers the entity and carries the details."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(EVENT_ENTITY)
    assert state.attributes["event_type"] == "delivered"
    assert state.attributes["tracking_number"] == TRACKING_NUMBER
    assert state.attributes["name"] == "Testpaket"
    assert state.attributes["old_status_code"] == "transit"
    assert state.attributes["new_status_code"] == "delivered"
    assert state.attributes["description"] == "The shipment is on its way."


async def test_event_uses_the_derived_out_for_delivery(
    hass: HomeAssistant,
    mock_api: AsyncMock,
    mock_config_entry: MockConfigEntry,
    shipment_responses: dict,
) -> None:
    """The derived status shows up as its own event type."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    today = dt_util.now().date().isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER,
        estimated_delivery=None,
        delivery_time_frame={
            "estimatedFrom": f"{today}T00:00:00",
            "estimatedThrough": f"{today}T23:00:00",
        },
    )
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(EVENT_ENTITY).attributes["event_type"] == "out_for_delivery"


async def test_event_entity_is_created_and_removed_at_runtime(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The event platform follows add and remove like the sensors do."""
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get("event.ersatzteil_shipment_status") is None

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_SHIPMENT,
        {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Ersatzteil"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("event.ersatzteil_shipment_status") is not None

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REMOVE_SHIPMENT,
        {"tracking_number": OTHER_TRACKING_NUMBER},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("event.ersatzteil_shipment_status") is None
    assert hass.states.get(EVENT_ENTITY) is not None


async def test_event_only_fires_for_its_own_shipment(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A change on one shipment must not trigger another one's entity."""
    entry = build_config_entry(
        shipments=[
            {"tracking_number": TRACKING_NUMBER, "name": "Eins"},
            {"tracking_number": OTHER_TRACKING_NUMBER, "name": "Zwei"},
        ]
    )
    await setup_integration(hass, entry)
    coordinator = entry.runtime_data.coordinator

    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("event.eins_shipment_status").state != "unknown"
    assert hass.states.get("event.zwei_shipment_status").state == "unknown"


# --- handover details ----------------------------------------------------------


async def test_delivered_to_and_location(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Proof of delivery details are exposed once the parcel arrived."""
    data = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    data["details"]["proofOfDelivery"] = {
        "signed": {"@type": "Person", "givenName": "Erika", "familyName": "Mustermann"},
        "timestamp": "2026-09-23T11:05:00+02:00",
        "documentUrl": "https://webpod.dhl.com/pod?token=abc",
    }
    data["status"]["location"] = {
        "address": {
            "addressLocality": "Hamburg",
            "postalCode": "20095",
            "countryCode": "DE",
        }
    }
    shipment_responses[TRACKING_NUMBER] = data
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    attrs = hass.states.get(
        f"sensor.dhl_{TRACKING_NUMBER.lower()}_status_code"
    ).attributes
    assert attrs["delivered_to"] == "Erika Mustermann"
    assert attrs["delivery_location"] == {
        "city": "Hamburg",
        "postal_code": "20095",
        "country": "DE",
    }
    assert dt_util.parse_datetime(attrs["delivered_at"]) == dt_util.parse_datetime(
        "2026-09-23T11:05:00+02:00"
    )
    assert attrs["proof_of_delivery_url"] == "https://webpod.dhl.com/pod?token=abc"


async def test_delivered_to_service_point(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A parcel shop handover is reported through the servicePoint object."""
    data = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    data["status"]["location"] = {
        "address": {"addressLocality": "Hamburg", "countryCode": "DE"},
        "servicePoint": {
            "label": "Packstation 123",
            "url": "https://www.dhl.de/packstation/123",
        },
    }
    shipment_responses[TRACKING_NUMBER] = data
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    attrs = hass.states.get(
        f"sensor.dhl_{TRACKING_NUMBER.lower()}_status_code"
    ).attributes
    assert attrs["delivery_location"]["service_point"] == "Packstation 123"
    assert (
        attrs["delivery_location"]["service_point_url"]
        == "https://www.dhl.de/packstation/123"
    )


async def test_delivered_at_falls_back_to_the_status_timestamp(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Without a proof of delivery the delivered status timestamp is used."""
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER,
        status="Delivered",
        status_code="delivered",
        timestamp="2026-09-23T11:05:00+02:00",
    )
    entry = build_config_entry(shipments=[{"tracking_number": TRACKING_NUMBER}])
    await setup_integration(hass, entry)

    attrs = hass.states.get(
        f"sensor.dhl_{TRACKING_NUMBER.lower()}_status_code"
    ).attributes
    assert dt_util.parse_datetime(attrs["delivered_at"]) == dt_util.parse_datetime(
        "2026-09-23T11:05:00+02:00"
    )


async def test_no_handover_details_while_in_transit(
    hass: HomeAssistant, mock_api: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Nothing is invented for a shipment that is still on its way.

    In particular `details.receiver` - the addressee - must not be published
    as `delivered_to`: it is not who accepted the parcel, and it would leak
    the recipient's name for every shipment in transit.
    """
    await setup_integration(hass, mock_config_entry)

    attrs = hass.states.get("sensor.testpaket_status_code").attributes
    assert "delivered_at" not in attrs
    assert "delivered_to" not in attrs
    assert "delivery_location" not in attrs
    assert "Mustermann" not in str(attrs)


async def test_handover_details_are_not_in_events(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Personal handover data stays on the entity, out of the event bus."""
    data = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered"
    )
    data["details"]["proofOfDelivery"] = {
        "signed": {"@type": "Person", "givenName": "Erika", "familyName": "Mustermann"}
    }
    entry = build_config_entry(
        shipments=[{"tracking_number": TRACKING_NUMBER, "name": "Paket"}]
    )
    await setup_integration(hass, entry)

    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    shipment_responses[TRACKING_NUMBER] = data
    coordinator = entry.runtime_data.coordinator
    coordinator.states[TRACKING_NUMBER].last_polled = None
    await coordinator.async_refresh()

    assert len(events) == 1
    assert "Mustermann" not in str(events[0].data)
    assert "delivered_to" not in events[0].data


async def test_delivered_shipments_are_purged_automatically(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """The auto cleanup drops shipments delivered long enough ago."""
    old = (dt_util.utcnow() - timedelta(days=5)).isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered", timestamp=old
    )
    shipment_responses[OTHER_TRACKING_NUMBER] = shipment_payload(OTHER_TRACKING_NUMBER)
    entry = build_config_entry(
        shipments=[
            {"tracking_number": TRACKING_NUMBER},
            {"tracking_number": OTHER_TRACKING_NUMBER},
        ],
        options={"auto_remove_delivered_days": 3},
    )
    await setup_integration(hass, entry)
    await hass.async_block_till_done()

    assert TRACKING_NUMBER not in entry.runtime_data.coordinator.states
    assert OTHER_TRACKING_NUMBER in entry.runtime_data.coordinator.states
    assert hass.states.get(f"sensor.dhl_{TRACKING_NUMBER.lower()}_status") is None


async def test_recently_delivered_shipments_are_kept(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """A parcel delivered today survives the cleanup."""
    recent = (dt_util.utcnow() - timedelta(hours=2)).isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered", timestamp=recent
    )
    entry = build_config_entry(
        shipments=[{"tracking_number": TRACKING_NUMBER}],
        options={"auto_remove_delivered_days": 3},
    )
    await setup_integration(hass, entry)
    await hass.async_block_till_done()

    assert TRACKING_NUMBER in entry.runtime_data.coordinator.states


async def test_auto_cleanup_can_be_disabled(
    hass: HomeAssistant, mock_api: AsyncMock, shipment_responses: dict
) -> None:
    """Zero days keeps delivered shipments forever."""
    old = (dt_util.utcnow() - timedelta(days=90)).isoformat()
    shipment_responses[TRACKING_NUMBER] = shipment_payload(
        TRACKING_NUMBER, status="Delivered", status_code="delivered", timestamp=old
    )
    entry = build_config_entry(
        shipments=[{"tracking_number": TRACKING_NUMBER}],
        options={"auto_remove_delivered_days": 0},
    )
    await setup_integration(hass, entry)
    await hass.async_block_till_done()

    assert TRACKING_NUMBER in entry.runtime_data.coordinator.states
