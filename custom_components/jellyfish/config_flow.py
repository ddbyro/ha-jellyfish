"""Config flow: manual entry, DHCP discovery, reconfigure, options."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # moved in 2025.x
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
except ImportError:  # pragma: no cover
    from homeassistant.components.dhcp import DhcpServiceInfo

from .client import DEFAULT_PORT, JellyFishClient, JellyFishError
from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN


async def _probe(hass: HomeAssistant, host: str, port: int) -> dict[str, str]:
    """Connect once and read identity. Raises JellyFishError."""
    client = JellyFishClient(host, async_get_clientsession(hass), port=port)
    try:
        await client.start()
        hostname = await client.get_hostname()
        name = await client.get_name()
    finally:
        await client.close()
    return {"hostname": hostname, "name": name}


def _unique_id(hostname: str) -> str:
    """'JellyFish-2AB3.local' -> 'jellyfish-2ab3'."""
    return hostname.lower().removesuffix(".local")


class JellyFishConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            try:
                info = await _probe(self.hass, host, port)
            except JellyFishError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(_unique_id(info["hostname"]))
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=info["name"] or info["hostname"],
                    data={CONF_HOST: host, CONF_PORT: port},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
                }
            ),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        host = discovery_info.ip
        try:
            info = await _probe(self.hass, host, DEFAULT_PORT)
        except JellyFishError:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(_unique_id(info["hostname"]))
        # Keeps the entry's IP current when DHCP hands out a new address.
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._host, self._name = host, info["name"] or info["hostname"]
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._name or self._host,
                data={CONF_HOST: self._host, CONF_PORT: DEFAULT_PORT},
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._name, "host": self._host},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            try:
                info = await _probe(self.hass, host, port)
            except JellyFishError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(_unique_id(info["hostname"]))
                self._abort_if_unique_id_mismatch(reason="wrong_controller")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host, CONF_PORT: port}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Optional(
                        CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                    ): vol.Coerce(int),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return JellyFishOptionsFlow()


class JellyFishOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POLL_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=30, max=3600)
                    )
                }
            ),
        )
