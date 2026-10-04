"""Text entity: the controller's display name (as shown in the app)."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JellyFishConfigEntry
from .client import JellyFishError
from .coordinator import JellyFishCoordinator
from .entity import JellyFishEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyFishConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([JellyFishNameText(entry.runtime_data)])


class JellyFishNameText(JellyFishEntity, TextEntity):
    _attr_translation_key = "controller_name"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_max = 32

    def __init__(self, coordinator: JellyFishCoordinator) -> None:
        super().__init__(coordinator, "controller_name")

    @property
    def native_value(self) -> str:
        return self.coordinator.data.name

    async def async_set_value(self, value: str) -> None:
        try:
            await self.coordinator.client.set_name(value)
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err
        # The controller doesn't always echo name changes; re-read it.
        self.coordinator.data.name = await self.coordinator.client.get_name()
        self.async_write_ha_state()
