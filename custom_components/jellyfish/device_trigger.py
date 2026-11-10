"""Device triggers for the controller's connection health.

Only the controller device gets these — zone devices (via_device of the
controller) don't have a connection of their own to trigger on.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_CONNECTION, EVENT_RESTART

TRIGGER_RESTARTED = "restarted"
TRIGGER_DISCONNECTED = "disconnected"
TRIGGER_RECONNECTED = "reconnected"
TRIGGER_TYPES = {TRIGGER_RESTARTED, TRIGGER_DISCONNECTED, TRIGGER_RECONNECTED}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES)}
)


def _entry_id_for_device(hass: HomeAssistant, device_id: str) -> str | None:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            return entry_id
    return None


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict]:
    """Return the available triggers for a JellyFish device."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None or device.via_device_id is not None:
        return []  # not ours, or it's a zone device rather than the controller
    if _entry_id_for_device(hass, device_id) is None:
        return []
    base = {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id}
    return [{**base, CONF_TYPE: trigger_type} for trigger_type in TRIGGER_TYPES]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger, translating it to the underlying bus event."""
    entry_id = _entry_id_for_device(hass, config[CONF_DEVICE_ID])
    trigger_type = config[CONF_TYPE]
    if trigger_type == TRIGGER_RESTARTED:
        event_type: str = EVENT_RESTART
        event_data = {"entry_id": entry_id}
    else:
        event_type = EVENT_CONNECTION
        event_data = {
            "entry_id": entry_id,
            "connected": trigger_type == TRIGGER_RECONNECTED,
        }

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: event_type,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
