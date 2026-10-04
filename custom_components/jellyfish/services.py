"""Integration-level services (patterns, schedules, zone config)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .client import JellyFishError
from .const import (
    ATTR_COLORS,
    ATTR_CONFIG_ENTRY,
    ATTR_CONFIRM,
    ATTR_DIRECTION,
    ATTR_EFFECT,
    ATTR_EFFECT_BETWEEN_PIXELS,
    ATTR_EFFECT_VALUE,
    ATTR_EVENTS,
    ATTR_FROM_ZONE,
    ATTR_KIND,
    ATTR_NUM_OF_LEDS,
    ATTR_PATTERN,
    ATTR_SKIP,
    ATTR_SPACE_BETWEEN_PIXELS,
    ATTR_SPEED,
    ATTR_TYPE,
    ATTR_ZONES,
    DIRECTIONS,
    DOMAIN,
    EFFECTS,
    EFFECTS_BETWEEN_PIXELS,
    PATTERN_TYPES,
    SCHEDULE_ACTION_TYPES,
    SCHEDULE_DAYS,
    SCHEDULE_START_FROM,
    SERVICE_DELETE_PATTERN,
    SERVICE_GET_PATTERN,
    SERVICE_GET_SCHEDULE,
    SERVICE_GET_ZONE_CONFIG,
    SERVICE_REFRESH,
    SERVICE_SAVE_PATTERN,
    SERVICE_SET_SCHEDULE,
    SERVICE_SET_ZONE_CONFIG,
    build_pattern,
    flatten_colors,
)
from .coordinator import JellyFishCoordinator


def _colors(value: Any) -> list[int]:
    try:
        return flatten_colors(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid(str(err)) from err


def _pattern_path(value: Any) -> str:
    value = cv.string(value).strip()
    folder, sep, name = value.rpartition("/")
    if not sep or not folder or not name:
        raise vol.Invalid("pattern must be 'Folder/Name'")
    return value


# Pattern fields shared by run/adjust/save. Brightness here is 0-100 (controller
# units), not HA's 0-255, to match the JellyFish app.
PATTERN_FIELDS: dict[Any, Any] = {
    vol.Optional(ATTR_TYPE): vol.In(PATTERN_TYPES),
    vol.Optional(ATTR_COLORS): _colors,
    vol.Optional("brightness"): vol.All(vol.Coerce(int), vol.Range(0, 100)),
    vol.Optional(ATTR_SPEED): vol.All(vol.Coerce(int), vol.Range(0, 100)),
    vol.Optional(ATTR_DIRECTION): vol.In(DIRECTIONS),
    vol.Optional(ATTR_EFFECT): vol.In(EFFECTS),
    vol.Optional(ATTR_EFFECT_VALUE): vol.All(vol.Coerce(int), vol.Range(0, 100)),
    vol.Optional(ATTR_SPACE_BETWEEN_PIXELS): vol.All(vol.Coerce(int), vol.Range(1, 100)),
    vol.Optional(ATTR_EFFECT_BETWEEN_PIXELS): vol.In(EFFECTS_BETWEEN_PIXELS),
    vol.Optional(ATTR_NUM_OF_LEDS): vol.All(vol.Coerce(int), vol.Range(1, 100)),
    vol.Optional(ATTR_SKIP): vol.All(vol.Coerce(int), vol.Range(1, 100)),
}
PATTERN_KEYS = [k.schema for k in PATTERN_FIELDS]

_ACTION = vol.Schema(
    {
        vol.Required("type"): vol.In(SCHEDULE_ACTION_TYPES),
        vol.Required("startFrom"): vol.In(SCHEDULE_START_FROM),
        vol.Required("hour"): vol.All(vol.Coerce(int), vol.Range(-23, 23)),
        vol.Required("minute"): vol.All(vol.Coerce(int), vol.Range(-59, 59)),
        vol.Optional("patternFile", default=""): cv.string,
        vol.Required("zones"): [cv.string],
    }
)


def _day(value: Any) -> str:
    value = cv.string(value)
    if value in SCHEDULE_DAYS or (len(value) == 8 and value.isdigit()):
        return value
    raise vol.Invalid("days are S/M/T/W/TH/F/SA (daily) or YYYYMMDD (calendar)")


_EVENT = vol.Schema(
    {
        vol.Optional("label", default=""): cv.string,
        vol.Required("days"): [_day],
        vol.Required("actions"): [_ACTION],
    }
)

_PORT_MAP = vol.Schema(
    {
        vol.Required("phyPort"): vol.All(vol.Coerce(int), vol.Range(1, 16)),
        vol.Required("phyStartIdx"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Required("phyEndIdx"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("zoneRGBStartIdx"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("ctlrName"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)
_ZONE = vol.Schema(
    {vol.Optional("numPixels"): vol.Coerce(int), vol.Required("portMap"): [_PORT_MAP]},
    extra=vol.ALLOW_EXTRA,
)

_ENTRY = {vol.Required(ATTR_CONFIG_ENTRY): cv.string}

SCHEMAS = {
    SERVICE_SAVE_PATTERN: vol.Schema(
        {**_ENTRY, vol.Required(ATTR_PATTERN): _pattern_path,
         vol.Optional(ATTR_FROM_ZONE): cv.string, **PATTERN_FIELDS}
    ),
    SERVICE_DELETE_PATTERN: vol.Schema({**_ENTRY, vol.Required(ATTR_PATTERN): _pattern_path}),
    SERVICE_GET_PATTERN: vol.Schema({**_ENTRY, vol.Required(ATTR_PATTERN): _pattern_path}),
    SERVICE_GET_SCHEDULE: vol.Schema(
        {**_ENTRY, vol.Optional(ATTR_KIND, default="all"): vol.In(["daily", "calendar", "all"])}
    ),
    SERVICE_SET_SCHEDULE: vol.Schema(
        {**_ENTRY, vol.Required(ATTR_KIND): vol.In(["daily", "calendar"]),
         vol.Required(ATTR_EVENTS): [_EVENT]}
    ),
    SERVICE_GET_ZONE_CONFIG: vol.Schema(_ENTRY),
    SERVICE_SET_ZONE_CONFIG: vol.Schema(
        {**_ENTRY, vol.Required(ATTR_ZONES): {cv.string: _ZONE},
         vol.Required(ATTR_CONFIRM): cv.boolean}
    ),
    SERVICE_REFRESH: vol.Schema(_ENTRY),
}


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> JellyFishCoordinator:
    entry_id = call.data[ATTR_CONFIG_ENTRY]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(f"Unknown JellyFish config entry: {entry_id}")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("JellyFish controller is not loaded")
    return entry.runtime_data


def pattern_overrides(data: dict[str, Any]) -> dict[str, Any]:
    return {k: data[k] for k in PATTERN_KEYS if k in data}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def save_pattern(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        path = call.data[ATTR_PATTERN]
        if path in coord.data.read_only_patterns:
            raise ServiceValidationError(f"{path} is a built-in read-only pattern")
        base = None
        if zone := call.data.get(ATTR_FROM_ZONE):
            if zone not in coord.data.zones:
                raise ServiceValidationError(f"Unknown zone: {zone}")
            base = coord.data.zone_pattern(zone)
            if base is None:
                state = coord.data.states.get(zone, {})
                if state.get("file"):
                    base = await coord.client.get_pattern_data(state["file"])
        data = build_pattern(base, **pattern_overrides(call.data))
        await _guard(coord.client.save_pattern(path, data))

    async def delete_pattern(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        path = call.data[ATTR_PATTERN]
        if path in coord.data.read_only_patterns:
            raise ServiceValidationError(f"{path} is a built-in read-only pattern")
        if path not in coord.data.patterns:
            raise ServiceValidationError(f"No such pattern: {path}")
        await _guard(coord.client.delete_pattern(path))

    async def get_pattern(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(hass, call)
        data = await _guard(coord.client.get_pattern_data(call.data[ATTR_PATTERN]))
        return {"pattern": call.data[ATTR_PATTERN], "data": data}

    async def get_schedule(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(hass, call)
        kind = call.data[ATTR_KIND]
        out: dict[str, Any] = {}
        if kind in ("daily", "all"):
            out["daily"] = await _guard(coord.client.get_schedule("daily"))
        if kind in ("calendar", "all"):
            out["calendar"] = await _guard(coord.client.get_schedule("calendar"))
        return out

    async def set_schedule(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        zones = set(coord.data.zones)
        for event in call.data[ATTR_EVENTS]:
            for action in event["actions"]:
                if unknown := set(action["zones"]) - zones:
                    raise ServiceValidationError(f"Unknown zones: {sorted(unknown)}")
                if action["type"] == "RUN" and action["patternFile"] not in coord.data.patterns:
                    raise ServiceValidationError(
                        f"Unknown pattern: {action['patternFile']}"
                    )
                if action["type"] == "STOP":
                    action["patternFile"] = ""
        await _guard(coord.client.set_schedule(call.data[ATTR_KIND], call.data[ATTR_EVENTS]))

    async def get_zone_config(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(hass, call)
        return {"zones": await _guard(coord.client.get_zones())}

    async def set_zone_config(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        if not call.data[ATTR_CONFIRM]:
            raise ServiceValidationError(
                "Set confirm: true. Writing zone config changes port mapping and "
                "turns all lights off."
            )
        hostname = coord.data.hostname
        zones: dict[str, Any] = {}
        for name, zone in call.data[ATTR_ZONES].items():
            port_map = []
            rgb_start = 0
            for pm in zone["portMap"]:
                if pm["phyEndIdx"] < pm["phyStartIdx"]:
                    raise ServiceValidationError(
                        f"{name}: phyEndIdx is before phyStartIdx on port {pm['phyPort']}"
                    )
                count = pm["phyEndIdx"] - pm["phyStartIdx"] + 1
                port_map.append(
                    {
                        "ctlrName": pm.get("ctlrName", hostname),
                        "phyPort": pm["phyPort"],
                        "phyStartIdx": pm["phyStartIdx"],
                        "phyEndIdx": pm["phyEndIdx"],
                        "zoneRGBStartIdx": pm.get("zoneRGBStartIdx", rgb_start),
                    }
                )
                rgb_start += count
            zones[name] = {"numPixels": zone.get("numPixels", rgb_start), "portMap": port_map}
        await _guard(coord.client.set_zones(zones))

    async def refresh(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_request_refresh()

    handlers = {
        SERVICE_SAVE_PATTERN: (save_pattern, SupportsResponse.NONE),
        SERVICE_DELETE_PATTERN: (delete_pattern, SupportsResponse.NONE),
        SERVICE_GET_PATTERN: (get_pattern, SupportsResponse.ONLY),
        SERVICE_GET_SCHEDULE: (get_schedule, SupportsResponse.ONLY),
        SERVICE_SET_SCHEDULE: (set_schedule, SupportsResponse.NONE),
        SERVICE_GET_ZONE_CONFIG: (get_zone_config, SupportsResponse.ONLY),
        SERVICE_SET_ZONE_CONFIG: (set_zone_config, SupportsResponse.NONE),
        SERVICE_REFRESH: (refresh, SupportsResponse.NONE),
    }
    for name, (handler, response) in handlers.items():
        hass.services.async_register(
            DOMAIN, name, handler, schema=SCHEMAS[name], supports_response=response
        )


async def _guard(awaitable: Any) -> Any:
    try:
        return await awaitable
    except JellyFishError as err:
        raise HomeAssistantError(f"JellyFish controller error: {err}") from err
