"""Diagnostics download: full controller snapshot plus connection health."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import JellyFishConfigEntry

TO_REDACT = {"lat", "lon"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: JellyFishConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    client = coordinator.client
    data = coordinator.data
    snapshot = asdict(data) if data else {}
    if snapshot:
        snapshot["read_only_patterns"] = sorted(snapshot["read_only_patterns"])
    return {
        "entry": {"host": client.host, "port": client.port, "options": dict(entry.options)},
        "connection": {
            "connected": client.connected,
            "connect_count": client.connect_count,
            "disconnect_count": client.disconnect_count,
            "last_connected": client.last_connected,
            "last_disconnected": client.last_disconnected,
            "last_message": client.last_message,
            "last_latency_ms": client.last_latency_ms,
        },
        "health": {
            k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in asdict(coordinator.health).items()
        },
        "controller": async_redact_data(snapshot, TO_REDACT),
    }
