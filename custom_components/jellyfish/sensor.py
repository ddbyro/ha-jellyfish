"""Sensors: active pattern, zone layout, firmware, and connection health."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JellyFishConfigEntry
from .coordinator import JellyFishCoordinator
from .entity import JellyFishEntity, JellyFishZoneEntity


def _ts(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value, timezone.utc) if value else None


@dataclass(frozen=True, kw_only=True)
class ControllerSensorDescription(SensorEntityDescription):
    value: Callable[[JellyFishCoordinator], Any]
    attrs: Callable[[JellyFishCoordinator], dict[str, Any]] | None = None
    always_available: bool = False


CONTROLLER_SENSORS = (
    ControllerSensorDescription(
        key="firmware", translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.data.version.get("ver"),
        attrs=lambda c: {"details": c.data.version.get("details")},
    ),
    ControllerSensorDescription(
        key="restarts_detected", translation_key="restarts_detected",
        entity_category=EntityCategory.DIAGNOSTIC, state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda c: c.health.restarts_detected, always_available=True,
    ),
    ControllerSensorDescription(
        key="last_restart", translation_key="last_restart",
        device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.health.last_restart, always_available=True,
    ),
    ControllerSensorDescription(
        key="connection_drops", translation_key="connection_drops",
        entity_category=EntityCategory.DIAGNOSTIC, state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda c: c.health.connection_drops, always_available=True,
    ),
    ControllerSensorDescription(
        key="last_connected", translation_key="last_connected",
        device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: _ts(c.client.last_connected), always_available=True,
    ),
    ControllerSensorDescription(
        key="last_message", translation_key="last_message",
        device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda c: _ts(c.client.last_message), always_available=True,
    ),
    ControllerSensorDescription(
        key="latency", translation_key="latency",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.client.last_latency_ms,
    ),
    ControllerSensorDescription(
        key="location", translation_key="location",
        entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
        value=lambda c: c.data.time_config.get("locName"),
        attrs=lambda c: {
            "timezone": c.data.time_config.get("timezone"),
            "timezone_name": c.data.time_config.get("timezoneName"),
        },
    ),
    ControllerSensorDescription(
        key="daily_schedule", translation_key="daily_schedule",
        value=lambda c: len(c.data.daily_schedule),
        attrs=lambda c: {"events": c.data.daily_schedule},
    ),
    ControllerSensorDescription(
        key="calendar_schedule", translation_key="calendar_schedule",
        value=lambda c: len(c.data.calendar_schedule),
        attrs=lambda c: {"events": c.data.calendar_schedule},
    ),
    ControllerSensorDescription(
        key="pattern_count", translation_key="pattern_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: len(c.data.patterns),
    ),
)


def port_summary(zone_cfg: dict[str, Any]) -> str:
    """'LED3 0-79, LED1 0-56' — the physical layout as the board labels it."""
    parts = [
        f"LED{pm.get('phyPort')} {pm.get('phyStartIdx')}-{pm.get('phyEndIdx')}"
        for pm in zone_cfg.get("portMap", [])
    ]
    return ", ".join(parts) or "none"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyFishConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        JellyFishControllerSensor(coordinator, desc) for desc in CONTROLLER_SENSORS
    ]
    for zone in coordinator.data.zones:
        entities += [
            JellyFishActivePatternSensor(coordinator, zone),
            JellyFishActivatedBySensor(coordinator, zone),
            JellyFishPortsSensor(coordinator, zone),
            JellyFishPixelsSensor(coordinator, zone),
        ]
    async_add_entities(entities)


class JellyFishControllerSensor(JellyFishEntity, SensorEntity):
    entity_description: ControllerSensorDescription

    def __init__(
        self, coordinator: JellyFishCoordinator, description: ControllerSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        # Health counters must stay readable while the controller is down.
        if self.entity_description.always_available:
            return self.coordinator.data is not None
        return super().available

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = self.entity_description.attrs
        return attrs(self.coordinator) if attrs else None


class JellyFishActivePatternSensor(JellyFishZoneEntity, SensorEntity):
    _attr_translation_key = "active_pattern"

    def __init__(self, coordinator: JellyFishCoordinator, zone: str) -> None:
        super().__init__(coordinator, zone, "active_pattern")

    @property
    def native_value(self) -> str:
        state = self.zone_state
        if not state.get("state"):
            return "Off"
        return state.get("file") or "Custom"


class JellyFishActivatedBySensor(JellyFishZoneEntity, SensorEntity):
    _attr_translation_key = "activated_by"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: JellyFishCoordinator, zone: str) -> None:
        super().__init__(coordinator, zone, "activated_by")

    @property
    def native_value(self) -> str | None:
        return self.zone_state.get("activatedBy")


class JellyFishPortsSensor(JellyFishZoneEntity, SensorEntity):
    _attr_translation_key = "ports"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: JellyFishCoordinator, zone: str) -> None:
        super().__init__(coordinator, zone, "ports")

    @property
    def native_value(self) -> str:
        return port_summary(self.coordinator.data.zones.get(self.zone, {}))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"port_map": self.coordinator.data.zones.get(self.zone, {}).get("portMap", [])}


class JellyFishPixelsSensor(JellyFishZoneEntity, SensorEntity):
    _attr_translation_key = "pixels"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: JellyFishCoordinator, zone: str) -> None:
        super().__init__(coordinator, zone, "pixels")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.zones.get(self.zone, {}).get("numPixels")
