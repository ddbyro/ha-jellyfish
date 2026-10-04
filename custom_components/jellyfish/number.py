"""Number entities: tune the running pattern per zone."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JellyFishConfigEntry
from .client import JellyFishError
from .coordinator import JellyFishCoordinator
from .entity import JellyFishZoneEntity


@dataclass(frozen=True, kw_only=True)
class PatternNumberDescription(NumberEntityDescription):
    field: str
    path: tuple[str, ...]


NUMBERS = (
    # Speed: 0/1 is fastest, larger is slower (controller uses 1/x).
    PatternNumberDescription(
        key="speed", translation_key="speed", field="speed", path=("runData", "speed"),
        native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.SLIDER,
    ),
    PatternNumberDescription(
        key="brightness", translation_key="brightness", field="brightness",
        path=("runData", "brightness"), native_min_value=1, native_max_value=100,
        native_step=1, native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
    ),
    PatternNumberDescription(
        key="effect_value", translation_key="effect_value", field="effect_value",
        path=("runData", "effectValue"), native_min_value=0, native_max_value=100,
        native_step=1, mode=NumberMode.SLIDER,
    ),
    PatternNumberDescription(
        key="space_between_pixels", translation_key="space_between_pixels",
        field="space_between_pixels", path=("spaceBetweenPixels",),
        native_min_value=1, native_max_value=100, native_step=1,
        entity_category=EntityCategory.CONFIG, entity_registry_enabled_default=False,
    ),
    PatternNumberDescription(
        key="skip", translation_key="skip", field="skip", path=("skip",),
        native_min_value=1, native_max_value=100, native_step=1,
        entity_category=EntityCategory.CONFIG, entity_registry_enabled_default=False,
    ),
    PatternNumberDescription(
        key="num_of_leds", translation_key="num_of_leds", field="num_of_leds",
        path=("numOfLeds",), native_min_value=1, native_max_value=100, native_step=1,
        entity_category=EntityCategory.CONFIG, entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyFishConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        JellyFishPatternNumber(coordinator, zone, desc)
        for zone in coordinator.data.zones
        for desc in NUMBERS
    )


class JellyFishPatternNumber(JellyFishZoneEntity, NumberEntity):
    entity_description: PatternNumberDescription

    def __init__(
        self,
        coordinator: JellyFishCoordinator,
        zone: str,
        description: PatternNumberDescription,
    ) -> None:
        super().__init__(coordinator, zone, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        value: object = self.zone_pattern
        for key in self.entity_description.path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.async_rerun_with(**{self.entity_description.field: int(value)})
        except JellyFishError as err:
            raise HomeAssistantError(f"JellyFish controller error: {err}") from err
