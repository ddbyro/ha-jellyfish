"""Scene entities: one per (zone, saved pattern), for a native scene card
instead of only the select.<zone>_pattern dropdown.

The set of saved patterns changes at runtime (save_pattern/delete_pattern,
or edits made from the app), so new scenes are added as new patterns
appear; a scene whose pattern was deleted goes unavailable rather than
being removed outright, same as how other entities here report "off" or
unavailable instead of disappearing when the underlying data is gone.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JellyFishConfigEntry
from .client import JellyFishError
from .coordinator import JellyFishCoordinator
from .entity import JellyFishZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyFishConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    added: set[tuple[str, str]] = set()

    def _sync_scenes() -> None:
        current = {
            (zone, pattern)
            for zone in coordinator.data.zones
            for pattern in coordinator.data.patterns
        }
        new = current - added
        if new:
            async_add_entities(
                JellyFishPatternScene(coordinator, zone, pattern) for zone, pattern in new
            )
            added.update(new)

    _sync_scenes()
    entry.async_on_unload(coordinator.async_add_listener(_sync_scenes))


class JellyFishPatternScene(JellyFishZoneEntity, Scene):
    def __init__(self, coordinator: JellyFishCoordinator, zone: str, pattern: str) -> None:
        super().__init__(coordinator, zone, f"scene_{pattern}")
        self._pattern = pattern
        self._attr_name = pattern

    @property
    def available(self) -> bool:
        return super().available and self._pattern in self.coordinator.data.patterns

    async def async_activate(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.run_pattern([self.zone], file=self._pattern)
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err
