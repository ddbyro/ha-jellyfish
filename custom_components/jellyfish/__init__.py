"""JellyFish Lighting integration for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .client import DEFAULT_PORT, JellyFishClient, JellyFishError
from .const import DOMAIN
from .coordinator import JellyFishCoordinator
from .services import async_setup_services

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.TEXT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type JellyFishConfigEntry = ConfigEntry[JellyFishCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: JellyFishConfigEntry) -> bool:
    client = JellyFishClient(
        entry.data[CONF_HOST],
        async_get_clientsession(hass),
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
    )
    try:
        await client.start()
    except JellyFishError as err:
        raise ConfigEntryNotReady(f"Cannot reach controller: {err}") from err

    coordinator = JellyFishCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await client.close()
        raise

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JellyFishConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
        await entry.runtime_data.client.close()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: JellyFishConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
