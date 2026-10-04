"""Constants for the JellyFish Lighting integration."""

from __future__ import annotations

from typing import Any

DOMAIN = "jellyfish"
MANUFACTURER = "JellyFish Lighting"

CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 300  # seconds; push updates cover most changes

# Values accepted by the controller (from the official API doc and the app).
PATTERN_TYPES = ["Color", "Chase", "Paint", "Stacker", "Sequence", "Multi-Paint", "Soffit"]
DIRECTIONS = ["Left", "Center", "Right"]
EFFECTS = ["No Effect", "Twinkle", "Lightning"]
EFFECTS_BETWEEN_PIXELS = [
    "No Color Transform",
    "Repeat",
    "Progression",
    "Fade",
    "Fill with Black",
]
MAX_COLORS = 30
SCHEDULE_ACTION_TYPES = ["RUN", "STOP"]
SCHEDULE_START_FROM = ["time", "sunrise", "sunset"]
SCHEDULE_DAYS = ["S", "M", "T", "W", "TH", "F", "SA"]

# Fields the controller expects in every pattern; missing fields make it reject
# the whole command, so ad-hoc patterns are built on top of these defaults.
DEFAULT_RUN_DATA: dict[str, Any] = {
    "speed": 10,
    "brightness": 100,
    "effect": "No Effect",
    "effectValue": 0,
    "rgbAdj": [100, 100, 100],
}
DEFAULT_PATTERN: dict[str, Any] = {
    "type": "Color",
    "colors": [255, 255, 255],
    "spaceBetweenPixels": 2,
    "effectBetweenPixels": "No Color Transform",
    "colorPos": [-1],
    "cursor": -1,
    "skip": 1,
    "numOfLeds": 1,
    "direction": "Left",
}

# Services
SERVICE_RUN_CUSTOM_PATTERN = "run_custom_pattern"
SERVICE_ADJUST_PATTERN = "adjust_pattern"
SERVICE_SAVE_PATTERN = "save_pattern"
SERVICE_DELETE_PATTERN = "delete_pattern"
SERVICE_GET_PATTERN = "get_pattern"
SERVICE_GET_SCHEDULE = "get_schedule"
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_GET_ZONE_CONFIG = "get_zone_config"
SERVICE_SET_ZONE_CONFIG = "set_zone_config"
SERVICE_REFRESH = "refresh"

ATTR_CONFIG_ENTRY = "config_entry_id"
ATTR_PATTERN = "pattern"
ATTR_TYPE = "type"
ATTR_COLORS = "colors"
ATTR_SPEED = "speed"
ATTR_DIRECTION = "direction"
ATTR_EFFECT = "effect"
ATTR_EFFECT_VALUE = "effect_value"
ATTR_SPACE_BETWEEN_PIXELS = "space_between_pixels"
ATTR_EFFECT_BETWEEN_PIXELS = "effect_between_pixels"
ATTR_NUM_OF_LEDS = "num_of_leds"
ATTR_SKIP = "skip"
ATTR_SAVE_AS = "save_as"
ATTR_FROM_ZONE = "from_zone"
ATTR_KIND = "kind"
ATTR_EVENTS = "events"
ATTR_ZONES = "zones"
ATTR_CONFIRM = "confirm"

EVENT_CONNECTION = f"{DOMAIN}_connection"


def build_pattern(
    base: dict[str, Any] | None = None, **overrides: Any
) -> dict[str, Any]:
    """Merge overrides onto a complete pattern so no required field is missing.

    Keyword names are the service/HA names (snake_case); `brightness`, `speed`,
    `effect`, `effect_value` live under runData on the controller.
    """
    pattern = {**DEFAULT_PATTERN, **(base or {})}
    run_data = {**DEFAULT_RUN_DATA, **(pattern.get("runData") or {})}
    top_level = {
        ATTR_TYPE: "type",
        ATTR_DIRECTION: "direction",
        ATTR_SPACE_BETWEEN_PIXELS: "spaceBetweenPixels",
        ATTR_EFFECT_BETWEEN_PIXELS: "effectBetweenPixels",
        ATTR_NUM_OF_LEDS: "numOfLeds",
        ATTR_SKIP: "skip",
    }
    nested = {
        "brightness": "brightness",
        ATTR_SPEED: "speed",
        ATTR_EFFECT: "effect",
        ATTR_EFFECT_VALUE: "effectValue",
    }
    for key, value in overrides.items():
        if value is None:
            continue
        if key == ATTR_COLORS:
            pattern["colors"] = flatten_colors(value)
        elif key in top_level:
            pattern[top_level[key]] = value
        elif key in nested:
            run_data[nested[key]] = value
    pattern["runData"] = run_data
    return pattern


def flatten_colors(colors: Any) -> list[int]:
    """Accept [[r,g,b], ...] or a flat [r,g,b,r,g,b] list; return flat ints."""
    flat: list[int] = []
    for item in colors:
        if isinstance(item, (list, tuple)):
            flat.extend(int(c) for c in item)
        else:
            flat.append(int(item))
    if not flat or len(flat) % 3:
        raise ValueError("colors must be RGB triples")
    if len(flat) > MAX_COLORS * 3:
        raise ValueError(f"at most {MAX_COLORS} colors are supported")
    if any(c < 0 or c > 255 for c in flat):
        raise ValueError("color values must be 0-255")
    return flat


def group_colors(flat: list[int]) -> list[list[int]]:
    return [flat[i : i + 3] for i in range(0, len(flat) - len(flat) % 3, 3)]
