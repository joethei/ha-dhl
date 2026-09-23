"""Shared wiring so every platform can add and remove entities at runtime."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DhlUpdateCoordinator, ShipmentDiff


def async_setup_shipment_platform(
    hass: HomeAssistant,
    entry: object,
    coordinator: DhlUpdateCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[str], Sequence[Entity]],
    extra: Sequence[Entity] = (),
) -> None:
    """Create the entities of one platform and keep them in sync.

    ``build`` returns the entities for a single tracking number. Adding or
    removing a shipment at runtime then creates or removes exactly those,
    without reloading the config entry.
    """
    created: dict[str, list[Entity]] = {}

    def _build(tracking_number: str) -> list[Entity]:
        entities = list(build(tracking_number))
        created[tracking_number] = entities
        return entities

    initial: list[Entity] = list(extra)
    for tracking_number in coordinator.states:
        initial.extend(_build(tracking_number))
    async_add_entities(initial)

    async def _async_handle_shipment_diff(diff: ShipmentDiff) -> None:
        registry = er.async_get(hass)
        for shipment in diff.removed:
            for entity in created.pop(shipment.tracking_number, []):
                entity_id = entity.entity_id
                await entity.async_remove(force_remove=True)
                if entity_id and registry.async_get(entity_id) is not None:
                    registry.async_remove(entity_id)

        new_entities: list[Entity] = []
        for shipment in diff.added:
            new_entities.extend(_build(shipment.tracking_number))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(  # type: ignore[attr-defined]
        coordinator.async_add_shipment_listener(_async_handle_shipment_diff)
    )
