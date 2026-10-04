"""Select entities: saved pattern and pattern options per zone."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JellyFishConfigEntry
from .client import JellyFishError
from .const import DIRECTIONS, EFFECTS, EFFECTS_BETWEEN_PIXELS, PATTERN_TYPES
from .coordinator import JellyFishCoordinator
from .entity import JellyFishZoneEntity


@dataclass(frozen=True, kw_only=True)
class PatternOptionDescription(SelectEntityDescription):
    field: str  # build_pattern keyword
    path: tuple[str, ...]  # where the value lives in pattern data


OPTION_SELECTS = (
    PatternOptionDescription(
        key="direction", translation_key="direction", options=DIRECTIONS,
        field="direction", path=("direction",),
    ),
    PatternOptionDescription(
        key="effect", translation_key="effect", options=EFFECTS,
        field="effect", path=("runData", "effect"),
    ),
    PatternOptionDescription(
        key="pattern_type", translation_key="pattern_type", options=PATTERN_TYPES,
        field="type", path=("type",), entity_category=EntityCategory.CONFIG,
    ),
    PatternOptionDescription(
        key="effect_between_pixels", translation_key="effect_between_pixels",
        options=EFFECTS_BETWEEN_PIXELS, field="effect_between_pixels",
        path=("effectBetweenPixels",), entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyFishConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = []
    for zone in coordinator.data.zones:
        entities.append(JellyFishPatternSelect(coordinator, zone))
        entities.extend(
            JellyFishOptionSelect(coordinator, zone, desc) for desc in OPTION_SELECTS
        )
    async_add_entities(entities)


class JellyFishPatternSelect(JellyFishZoneEntity, SelectEntity):
    _attr_translation_key = "pattern"

    def __init__(self, coordinator: JellyFishCoordinator, zone: str) -> None:
        super().__init__(coordinator, zone, "pattern")

    @property
    def options(self) -> list[str]:
        return self.coordinator.data.patterns

    @property
    def current_option(self) -> str | None:
        file = self.zone_state.get("file")
        return file if file in self.coordinator.data.patterns else None

    async def async_select_option(self, option: str) -> None:
        if option not in self.coordinator.data.patterns:
            raise ServiceValidationError(f"Unknown pattern: {option}")
        try:
            await self.coordinator.client.run_pattern([self.zone], file=option)
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err


class JellyFishOptionSelect(JellyFishZoneEntity, SelectEntity):
    entity_description: PatternOptionDescription

    def __init__(
        self,
        coordinator: JellyFishCoordinator,
        zone: str,
        description: PatternOptionDescription,
    ) -> None:
        super().__init__(coordinator, zone, description.key)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        value: object = self.zone_pattern
        for key in self.entity_description.path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.async_rerun_with(**{self.entity_description.field: option})
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err
