"""Buttons: refresh data and force a reconnect."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JellyFishConfigEntry
from .coordinator import JellyFishCoordinator
from .entity import JellyFishEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyFishConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [JellyFishRefreshButton(coordinator), JellyFishReconnectButton(coordinator)]
    )


class JellyFishRefreshButton(JellyFishEntity, ButtonEntity):
    _attr_translation_key = "refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: JellyFishCoordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()


class JellyFishReconnectButton(JellyFishEntity, ButtonEntity):
    _attr_translation_key = "reconnect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: JellyFishCoordinator) -> None:
        super().__init__(coordinator, "reconnect")

    @property
    def available(self) -> bool:
        return True  # most useful exactly when disconnected

    async def async_press(self) -> None:
        await self.coordinator.client.reconnect()
