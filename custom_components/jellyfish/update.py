"""Update entity: is a firmware update available.

The controller only reports a yes/no flag (`isUpdate`), never the actual
available version, release notes, or a way to trigger the install over the
API — so `latest_version` can't be a real version number when one's
available. `UPDATE_SENTINEL` stands in for it: it compares unequal to
`installed_version` and fails `AwesomeVersion` parsing, which HA's
`UpdateEntity.has_update` treats as "yes, there's an update" (see
`homeassistant/components/update/entity.py`). This gets the right on/off
state and the frontend's built-in "update available" card, just without a
real target version.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JellyFishConfigEntry
from .coordinator import JellyFishCoordinator
from .entity import JellyFishEntity

UPDATE_SENTINEL = "update"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyFishConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([JellyFishFirmwareUpdate(entry.runtime_data)])


class JellyFishFirmwareUpdate(JellyFishEntity, UpdateEntity):
    _attr_translation_key = "firmware_update"
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(self, coordinator: JellyFishCoordinator) -> None:
        super().__init__(coordinator, "firmware_update")

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.data.version.get("ver")

    @property
    def latest_version(self) -> str | None:
        if self.coordinator.data.version.get("isUpdate"):
            return UPDATE_SENTINEL
        return self.installed_version

    @property
    def release_summary(self) -> str | None:
        if self.coordinator.data.version.get("isUpdate"):
            return (
                "A firmware update is available. The JellyFish API doesn't "
                "expose the version number or release notes — check the app."
            )
        return None
