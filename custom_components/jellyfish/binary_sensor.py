"""Binary sensors: connectivity and firmware update flag."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
        [JellyFishConnectedSensor(coordinator), JellyFishUpdateSensor(coordinator)]
    )


class JellyFishConnectedSensor(JellyFishEntity, BinarySensorEntity):
    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: JellyFishCoordinator) -> None:
        super().__init__(coordinator, "connected")

    @property
    def available(self) -> bool:
        return True  # reporting "disconnected" is the point

    @property
    def is_on(self) -> bool:
        return self.coordinator.connected


class JellyFishUpdateSensor(JellyFishEntity, BinarySensorEntity):
    _attr_translation_key = "firmware_update"
    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: JellyFishCoordinator) -> None:
        super().__init__(coordinator, "firmware_update")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.version.get("isUpdate"))
