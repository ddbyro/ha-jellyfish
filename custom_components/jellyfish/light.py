"""Light entities: one per zone, plus 'All zones' when there are several."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import voluptuous as vol

from . import JellyFishConfigEntry
from .client import JellyFishError, parse_pattern_data
from .const import (
    ATTR_SAVE_AS,
    SERVICE_ADJUST_PATTERN,
    SERVICE_RUN_CUSTOM_PATTERN,
    build_pattern,
    group_colors,
)
from .coordinator import JellyFishCoordinator
from .entity import JellyFishEntity, JellyFishZoneEntity
from .services import PATTERN_FIELDS, _pattern_path, pattern_overrides


def _to_ha(brightness: int | None) -> int | None:
    return None if brightness is None else round(brightness * 255 / 100)


def _to_jf(brightness: int) -> int:
    return max(1, round(brightness * 100 / 255))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyFishConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[LightEntity] = [
        JellyFishZoneLight(coordinator, zone) for zone in coordinator.data.zones
    ]
    if len(coordinator.data.zones) > 1:
        entities.append(JellyFishAllZonesLight(coordinator))
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_RUN_CUSTOM_PATTERN,
        {**PATTERN_FIELDS, vol.Optional(ATTR_SAVE_AS): _pattern_path},
        "async_run_custom_pattern",
    )
    platform.async_register_entity_service(
        SERVICE_ADJUST_PATTERN, PATTERN_FIELDS, "async_adjust_pattern"
    )


class _LightMixin(LightEntity):
    """Shared behavior; subclasses define `zones` and `primary_state`."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    coordinator: JellyFishCoordinator

    @property
    def zones(self) -> list[str]:
        raise NotImplementedError

    @property
    def primary_state(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def primary_pattern(self) -> dict[str, Any] | None:
        return parse_pattern_data(self.primary_state.get("data"))

    @property
    def effect_list(self) -> list[str]:
        return self.coordinator.data.patterns

    @property
    def effect(self) -> str | None:
        return self.primary_state.get("file") or None

    @property
    def brightness(self) -> int | None:
        pattern = self.primary_pattern
        if not pattern:
            return 255 if self.is_on else None
        return _to_ha((pattern.get("runData") or {}).get("brightness"))

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        pattern = self.primary_pattern
        if not pattern or len(pattern.get("colors") or []) < 3:
            return (255, 255, 255) if self.is_on else None
        r, g, b = pattern["colors"][:3]
        return (r, g, b)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.primary_state
        pattern = self.primary_pattern or {}
        run = pattern.get("runData") or {}
        return {
            "pattern_file": state.get("file") or None,
            "activated_by": state.get("activatedBy"),
            "pattern_type": pattern.get("type"),
            "colors": group_colors(pattern.get("colors") or []),
            "speed": run.get("speed"),
            "direction": pattern.get("direction"),
            "effect_mode": run.get("effect"),
            "zones": self.zones,
        }

    async def _current_pattern(self) -> dict[str, Any] | None:
        """Pattern data for what is running, fetching it if only a file is known."""
        if pattern := self.primary_pattern:
            return pattern
        if file := self.primary_state.get("file"):
            return await self.coordinator.client.get_pattern_data(file)
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        client = self.coordinator.client
        brightness = _to_jf(kwargs[ATTR_BRIGHTNESS]) if ATTR_BRIGHTNESS in kwargs else None
        try:
            if ATTR_EFFECT in kwargs:
                file = kwargs[ATTR_EFFECT]
                if file not in self.coordinator.data.patterns:
                    raise ServiceValidationError(f"Unknown pattern: {file}")
                if brightness is None:
                    await client.run_pattern(self.zones, file=file)
                else:
                    base = await client.get_pattern_data(file)
                    await client.run_pattern(
                        self.zones, data=build_pattern(base, brightness=brightness)
                    )
            elif ATTR_RGB_COLOR in kwargs:
                current = self.primary_pattern or {}
                current_brightness = (current.get("runData") or {}).get("brightness", 100)
                await client.run_pattern(
                    self.zones,
                    data=build_pattern(
                        None,
                        type="Color",
                        colors=[list(kwargs[ATTR_RGB_COLOR])],
                        brightness=brightness or current_brightness,
                    ),
                )
            elif brightness is not None:
                base = await self._current_pattern()
                await client.run_pattern(
                    self.zones, data=build_pattern(base, brightness=brightness)
                )
            else:
                # Plain "on": resume whatever was last configured.
                state = self.primary_state
                if state.get("file"):
                    await client.run_pattern(self.zones, file=state["file"])
                elif pattern := self.primary_pattern:
                    await client.run_pattern(self.zones, data=build_pattern(pattern))
                else:
                    await client.run_pattern(self.zones, data=build_pattern(None))
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.turn_off(self.zones)
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err

    async def async_run_custom_pattern(self, **data: Any) -> None:
        pattern = build_pattern(None, **pattern_overrides(data))
        try:
            await self.coordinator.client.run_pattern(self.zones, data=pattern)
            if save_as := data.get(ATTR_SAVE_AS):
                if save_as in self.coordinator.data.read_only_patterns:
                    raise ServiceValidationError(f"{save_as} is a built-in read-only pattern")
                await self.coordinator.client.save_pattern(save_as, pattern)
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err

    async def async_adjust_pattern(self, **data: Any) -> None:
        try:
            base = await self._current_pattern()
            await self.coordinator.client.run_pattern(
                self.zones, data=build_pattern(base, **pattern_overrides(data))
            )
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err


class JellyFishZoneLight(_LightMixin, JellyFishZoneEntity):
    _attr_name = None  # the zone device name is the light's name

    def __init__(self, coordinator: JellyFishCoordinator, zone: str) -> None:
        JellyFishZoneEntity.__init__(self, coordinator, zone, "light")

    @property
    def zones(self) -> list[str]:
        return [self.zone]

    @property
    def primary_state(self) -> dict[str, Any]:
        return self.zone_state

    @property
    def is_on(self) -> bool:
        return bool(self.zone_state.get("state"))


class JellyFishAllZonesLight(_LightMixin, JellyFishEntity):
    _attr_translation_key = "all_zones"

    def __init__(self, coordinator: JellyFishCoordinator) -> None:
        JellyFishEntity.__init__(self, coordinator, "all_zones")

    @property
    def zones(self) -> list[str]:
        return list(self.coordinator.data.zones)

    @property
    def primary_state(self) -> dict[str, Any]:
        states = self.coordinator.data.states
        for zone in self.zones:
            if states.get(zone, {}).get("state"):
                return states[zone]
        return states.get(self.zones[0], {}) if self.zones else {}

    @property
    def is_on(self) -> bool:
        states = self.coordinator.data.states
        return any(states.get(z, {}).get("state") for z in self.zones)
