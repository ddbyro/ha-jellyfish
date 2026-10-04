"""Coordinator: holds controller state, applies pushed updates, tracks health."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import JellyFishClient, JellyFishError, parse_pattern_data
from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN, EVENT_CONNECTION

_LOGGER = logging.getLogger(__name__)

# What a zone reports right after the controller boots: nothing running, a
# placeholder grey pattern, and no activatedBy. Seeing this after a reconnect
# means the controller restarted rather than just dropping the connection.
_BOOT_COLORS = [100, 100, 100]


@dataclass
class JellyFishData:
    """Snapshot of everything we know about one controller."""

    name: str = ""
    hostname: str = ""
    version: dict[str, Any] = field(default_factory=dict)
    time_config: dict[str, Any] = field(default_factory=dict)
    zones: dict[str, dict[str, Any]] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    read_only_patterns: set[str] = field(default_factory=set)
    states: dict[str, dict[str, Any]] = field(default_factory=dict)
    daily_schedule: list[dict[str, Any]] = field(default_factory=list)
    calendar_schedule: list[dict[str, Any]] = field(default_factory=list)

    def zone_pattern(self, zone: str) -> dict[str, Any] | None:
        return parse_pattern_data(self.states.get(zone, {}).get("data"))


@dataclass
class Health:
    restarts_detected: int = 0
    last_restart: datetime | None = None
    connection_drops: int = 0
    last_drop: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def looks_like_boot_state(state: dict[str, Any]) -> bool:
    data = parse_pattern_data(state.get("data")) or {}
    return (
        state.get("state") == 0
        and not state.get("file")
        and "activatedBy" not in state
        and data.get("colors") == _BOOT_COLORS
    )


class JellyFishCoordinator(DataUpdateCoordinator[JellyFishData]):
    """Push-first coordinator with a slow full refresh as a safety net."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: JellyFishClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )
        self.client = client
        self.health = Health()
        self._unsubs = [
            client.add_message_listener(self._on_message),
            client.add_connection_listener(self._on_connection),
        ]
        self._was_disconnected = False

    @property
    def connected(self) -> bool:
        return self.client.connected

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await super().async_shutdown()

    # ------------------------------------------------------------- full refresh

    async def _async_update_data(self) -> JellyFishData:
        try:
            return await self._fetch_all()
        except JellyFishError as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch_all(self) -> JellyFishData:
        c = self.client
        data = JellyFishData()
        data.name = await c.get_name()
        data.hostname = await c.get_hostname()
        data.version = await c.get_version()
        data.time_config = await c.get_time_config()
        data.zones = await c.get_zones()
        data.patterns, data.read_only_patterns = self._parse_pattern_list(
            await c.get_pattern_list()
        )
        for zone in data.zones:
            data.states[zone] = await c.get_zone_state(zone)
        data.daily_schedule = await c.get_schedule("daily")
        data.calendar_schedule = await c.get_schedule("calendar")
        return data

    @staticmethod
    def _parse_pattern_list(items: list[dict[str, Any]]) -> tuple[list[str], set[str]]:
        patterns: list[str] = []
        read_only: set[str] = set()
        for item in items:
            if not item.get("name"):
                continue  # folder header entry
            path = f"{item['folders']}/{item['name']}"
            patterns.append(path)
            if item.get("readOnly"):
                read_only.add(path)
        return sorted(patterns, key=str.casefold), read_only

    # -------------------------------------------------------------- push updates

    @callback
    def _on_message(self, msg: dict[str, Any]) -> None:
        if self.data is None:
            return
        data = self.data
        changed = True
        if "runPattern" in msg:
            state = msg["runPattern"]
            for zone in state.get("zoneName") or [state.get("id")]:
                if zone in data.zones:
                    data.states[zone] = {**state, "id": zone}
        elif "zones" in msg and isinstance(msg["zones"], dict):
            data.zones = msg["zones"]
            # Saving zones resets run state on the controller; re-read it.
            self.hass.async_create_task(self.async_request_refresh())
        elif "ctlrName" in msg:
            data.name = msg["ctlrName"]
        elif "schedule" in msg and "events" in msg:
            if msg["schedule"] == "daily":
                data.daily_schedule = msg["events"]
            elif msg["schedule"] == "calendar":
                data.calendar_schedule = msg["events"]
        elif "patternFileList" in msg:
            data.patterns, data.read_only_patterns = self._parse_pattern_list(
                msg["patternFileList"]
            )
        elif "patternFileData" in msg or "patternFileDelete" in msg:
            # A pattern was saved or deleted (by us or the app): reload the list.
            self.hass.async_create_task(self._reload_patterns())
            changed = False
        else:
            changed = False
        if changed:
            self.async_set_updated_data(data)

    async def _reload_patterns(self) -> None:
        try:
            items = await self.client.get_pattern_list()
        except JellyFishError as err:
            _LOGGER.debug("Pattern list reload failed: %s", err)
            return
        if self.data is not None:
            self.data.patterns, self.data.read_only_patterns = self._parse_pattern_list(
                items
            )
            self.async_set_updated_data(self.data)

    @callback
    def _on_connection(self, connected: bool) -> None:
        self.hass.bus.async_fire(
            EVENT_CONNECTION,
            {"host": self.client.host, "connected": connected,
             "entry_id": self.config_entry.entry_id},
        )
        if not connected:
            self._was_disconnected = True
            self.health.connection_drops += 1
            self.health.last_drop = _utcnow()
            self.async_update_listeners()  # entities go unavailable
            return
        if self._was_disconnected:
            self._was_disconnected = False
            self.hass.async_create_task(self._after_reconnect())

    async def _after_reconnect(self) -> None:
        await asyncio.sleep(1)  # let the controller settle after boot
        await self.async_refresh()
        if self.data and any(looks_like_boot_state(s) for s in self.data.states.values()):
            self.health.restarts_detected += 1
            self.health.last_restart = _utcnow()
            _LOGGER.warning(
                "JellyFish controller %s appears to have restarted", self.client.host
            )
            self.async_update_listeners()
