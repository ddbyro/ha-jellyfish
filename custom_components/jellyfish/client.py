"""Async websocket client for JellyFish Lighting controllers.

Protocol notes (verified against firmware 4.6.1):
- Endpoint is ws://<host>:9000/ws, JSON text frames.
- Requests are {"cmd": "toCtlrGet", "get": [[resource, *args]]} or
  {"cmd": "toCtlrSet", ...}. Replies are {"cmd": "fromCtlr", <resource>: ...}.
- Replies to "get" go only to the requesting connection. Replies to "set"
  (runPattern, zones, schedules, ...) are broadcast to every connected client,
  so a persistent connection sees changes made by the JellyFish app.
- Saving zone config resets the running state to "off".
- The controller does not always close the TCP socket when it reboots, so a
  dead connection is detected with an application-level heartbeat.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import json
import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 9000
DEFAULT_TIMEOUT = 10.0
HEARTBEAT_INTERVAL = 30.0
RECONNECT_MIN = 2.0
RECONNECT_MAX = 60.0

MessageCallback = Callable[[dict[str, Any]], None]
ConnectionCallback = Callable[[bool], None]


class JellyFishError(Exception):
    """Base error."""


class JellyFishConnectionError(JellyFishError):
    """Controller unreachable or connection dropped."""


class JellyFishTimeoutError(JellyFishError):
    """Controller did not answer in time."""


@dataclass
class _Waiter:
    key: str
    match: Callable[[dict[str, Any]], bool]
    future: asyncio.Future[dict[str, Any]]


def parse_pattern_data(data: Any) -> dict[str, Any] | None:
    """Pattern data travels as a JSON string; return it as a dict."""
    if not data:
        return None
    if isinstance(data, dict):
        return data
    try:
        parsed = json.loads(data)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def split_pattern(path: str) -> tuple[str, str]:
    """'Folder/Name' -> ('Folder', 'Name'). Names may not contain '/'."""
    folder, _, name = path.rpartition("/")
    return folder, name


class JellyFishClient:
    """Persistent connection to one controller with request/response matching."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()
        self._waiters: list[_Waiter] = []
        self._message_listeners: list[MessageCallback] = []
        self._connection_listeners: list[ConnectionCallback] = []
        self._runner: asyncio.Task | None = None
        self._connected_event = asyncio.Event()
        self._closing = False
        # Health counters, surfaced as diagnostics in Home Assistant.
        self.connect_count = 0
        self.disconnect_count = 0
        self.last_connected: float | None = None
        self.last_disconnected: float | None = None
        self.last_message: float | None = None
        self.last_latency_ms: float | None = None

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    # ------------------------------------------------------------------ listeners

    def add_message_listener(self, callback: MessageCallback) -> Callable[[], None]:
        self._message_listeners.append(callback)
        return lambda: self._message_listeners.remove(callback)

    def add_connection_listener(
        self, callback: ConnectionCallback
    ) -> Callable[[], None]:
        self._connection_listeners.append(callback)
        return lambda: self._connection_listeners.remove(callback)

    # ----------------------------------------------------------------- lifecycle

    async def connect(self) -> None:
        """Open the connection once (raises on failure). Used by setup/config flow."""
        await self._open()

    async def start(self) -> None:
        """Connect and keep the connection alive in the background."""
        self._closing = False
        if not self.connected:
            await self._open()
        self._runner = asyncio.create_task(self._run(), name=f"jellyfish-{self.host}")

    async def close(self) -> None:
        self._closing = True
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._runner = None
        await self._drop("closed")

    async def reconnect(self) -> None:
        """Drop the socket; the background runner reconnects immediately."""
        if self._ws is not None:
            await self._ws.close()

    async def _open(self) -> None:
        try:
            async with asyncio.timeout(self.timeout):
                self._ws = await self._session.ws_connect(
                    self.url, autoping=True, max_msg_size=0
                )
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            raise JellyFishConnectionError(f"Cannot connect to {self.url}: {err}") from err
        self.connect_count += 1
        self.last_connected = time.time()
        self._connected_event.set()
        _LOGGER.debug("Connected to %s", self.url)
        for cb in list(self._connection_listeners):
            cb(True)

    async def _drop(self, reason: str) -> None:
        ws, self._ws = self._ws, None
        self._connected_event.clear()
        for waiter in self._waiters:
            if not waiter.future.done():
                waiter.future.set_exception(
                    JellyFishConnectionError(f"Connection lost ({reason})")
                )
        self._waiters.clear()
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
        self.disconnect_count += 1
        self.last_disconnected = time.time()
        _LOGGER.debug("Disconnected from %s: %s", self.url, reason)
        for cb in list(self._connection_listeners):
            cb(False)

    async def _run(self) -> None:
        """Read messages, heartbeat, and reconnect with backoff forever."""
        backoff = RECONNECT_MIN
        while not self._closing:
            if not self.connected:
                try:
                    await self._open()
                    backoff = RECONNECT_MIN
                except JellyFishConnectionError as err:
                    _LOGGER.debug("Reconnect failed: %s (retry in %ss)", err, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, RECONNECT_MAX)
                    continue
            heartbeat = asyncio.create_task(self._heartbeat())
            try:
                await self._read_loop()
            finally:
                heartbeat.cancel()
            await self._drop("read loop ended")

    async def _read_loop(self) -> None:
        ws = self._ws
        assert ws is not None
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._handle_text(msg.data)
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                break

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            started = time.monotonic()
            try:
                await self.get("ctlrName", timeout=self.timeout)
            except JellyFishError as err:
                _LOGGER.debug("Heartbeat failed: %s", err)
                if self._ws is not None:
                    await self._ws.close()  # ends the read loop -> reconnect
                return
            self.last_latency_ms = round((time.monotonic() - started) * 1000, 1)

    def _handle_text(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON frame: %s", raw[:200])
            return
        if not isinstance(data, dict) or data.get("cmd") != "fromCtlr":
            return
        self.last_message = time.time()
        for waiter in list(self._waiters):
            if waiter.future.done():
                self._waiters.remove(waiter)
            elif waiter.key in data and waiter.match(data):
                waiter.future.set_result(data)
                self._waiters.remove(waiter)
        for cb in list(self._message_listeners):
            try:
                cb(data)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in JellyFish message listener")

    # ------------------------------------------------------------------ requests

    async def send(self, payload: dict[str, Any]) -> None:
        if not self.connected:
            raise JellyFishConnectionError("Not connected")
        async with self._send_lock:
            assert self._ws is not None
            try:
                await self._ws.send_str(json.dumps(payload, separators=(",", ":")))
            except (aiohttp.ClientError, ConnectionResetError) as err:
                raise JellyFishConnectionError(str(err)) from err

    async def request(
        self,
        payload: dict[str, Any],
        key: str,
        match: Callable[[dict[str, Any]], bool] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send payload and wait for the first reply containing `key`."""
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        waiter = _Waiter(key, match or (lambda _d: True), future)
        self._waiters.append(waiter)
        try:
            await self.send(payload)
            return await asyncio.wait_for(future, timeout or self.timeout)
        except asyncio.TimeoutError as err:
            raise JellyFishTimeoutError(f"No '{key}' reply from {self.host}") from err
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def get(self, resource: str, *args: str, timeout: float | None = None) -> Any:
        reply = await self.request(
            {"cmd": "toCtlrGet", "get": [[resource, *args]]}, resource, timeout=timeout
        )
        return reply[resource]

    # ---------------------------------------------------------------- read API

    async def get_name(self) -> str:
        return await self.get("ctlrName")

    async def get_hostname(self) -> str:
        return await self.get("hostName")

    async def get_version(self) -> dict[str, Any]:
        return await self.get("version")

    async def get_time_config(self) -> dict[str, Any]:
        return await self.get("timeConfig")

    async def get_zones(self) -> dict[str, dict[str, Any]]:
        return await self.get("zones")

    async def get_pattern_list(self) -> list[dict[str, Any]]:
        return await self.get("patternFileList")

    async def get_pattern_data(self, path: str) -> dict[str, Any] | None:
        folder, name = split_pattern(path)
        reply = await self.request(
            {"cmd": "toCtlrGet", "get": [["patternFileData", folder, name]]},
            "patternFileData",
            match=lambda d: d["patternFileData"].get("name") == name
            and d["patternFileData"].get("folders") == folder,
        )
        return parse_pattern_data(reply["patternFileData"].get("jsonData"))

    async def get_zone_state(self, zone: str) -> dict[str, Any]:
        reply = await self.request(
            {"cmd": "toCtlrGet", "get": [["runPattern", zone]]},
            "runPattern",
            match=lambda d: d["runPattern"].get("id") == zone
            or zone in d["runPattern"].get("zoneName", []),
        )
        return reply["runPattern"]

    async def get_schedule(self, kind: str) -> list[dict[str, Any]]:
        """kind is 'daily' or 'calendar'."""
        resource = "scheduleDaily" if kind == "daily" else "scheduleCalendar"
        reply = await self.request(
            {"cmd": "toCtlrGet", "get": [[resource]]},
            "events",
            match=lambda d: d.get("schedule", kind) == kind,
        )
        return reply["events"]

    # --------------------------------------------------------------- write API

    async def run_pattern(
        self,
        zones: list[str],
        *,
        file: str = "",
        data: dict[str, Any] | None = None,
        state: int = 1,
    ) -> None:
        """Run a saved pattern (file) or an ad-hoc pattern (data) on zones."""
        await self.send(
            {
                "cmd": "toCtlrSet",
                "runPattern": {
                    "file": file,
                    "data": json.dumps(data, separators=(",", ":")) if data else "",
                    "id": "",
                    "state": state,
                    "zoneName": zones,
                },
            }
        )

    async def turn_off(self, zones: list[str]) -> None:
        await self.run_pattern(zones, state=0)

    async def set_zones(self, zones: dict[str, dict[str, Any]]) -> None:
        await self.send({"cmd": "toCtlrSet", "save": True, "zones": zones})

    async def save_pattern(self, path: str, data: dict[str, Any]) -> None:
        folder, name = split_pattern(path)
        await self.send(
            {
                "cmd": "toCtlrSet",
                "patternFileData": {
                    "folders": folder,
                    "name": name,
                    "jsonData": json.dumps(data, separators=(",", ":")),
                },
            }
        )

    async def delete_pattern(self, path: str) -> None:
        folder, name = split_pattern(path)
        await self.send(
            {"cmd": "toCtlrSet", "patternFileDelete": {"folders": folder, "name": name}}
        )

    async def set_schedule(self, kind: str, events: list[dict[str, Any]]) -> None:
        await self.send({"cmd": "toCtlrSet", "schedule": kind, "events": events})

    async def set_name(self, name: str) -> None:
        await self.send({"cmd": "toCtlrSet", "ctlrName": name})
