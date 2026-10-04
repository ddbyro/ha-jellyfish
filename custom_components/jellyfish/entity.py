"""Base entity classes."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, build_pattern
from .coordinator import JellyFishCoordinator


class JellyFishEntity(CoordinatorEntity[JellyFishCoordinator]):
    """Controller-level entity attached to the controller device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: JellyFishCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._uid = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        self._attr_unique_id = f"{self._uid}_{key}"
        data = coordinator.data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uid)},
            manufacturer=MANUFACTURER,
            model="Controller",
            name=(data.name if data and data.name else coordinator.client.host),
            sw_version=(data.version.get("ver") if data else None),
            configuration_url=None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.connected


class JellyFishZoneEntity(JellyFishEntity):
    """Entity for one zone; zones get their own device under the controller."""

    def __init__(self, coordinator: JellyFishCoordinator, zone: str, key: str) -> None:
        super().__init__(coordinator, f"{zone}_{key}")
        self.zone = zone
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._uid}_{zone}")},
            manufacturer=MANUFACTURER,
            model="Zone",
            name=zone,
            via_device=(DOMAIN, self._uid),
        )

    @property
    def available(self) -> bool:
        return super().available and self.zone in self.coordinator.data.zones

    @property
    def zone_state(self) -> dict[str, Any]:
        return self.coordinator.data.states.get(self.zone, {})

    @property
    def zone_pattern(self) -> dict[str, Any] | None:
        return self.coordinator.data.zone_pattern(self.zone)

    async def async_rerun_with(self, **overrides: Any) -> None:
        """Re-send the zone's current pattern with some fields changed."""
        state = self.zone_state
        data = build_pattern(self.zone_pattern, **overrides)
        await self.coordinator.client.run_pattern(
            [self.zone], data=data, state=1 if state.get("state", 1) else 0
        )
