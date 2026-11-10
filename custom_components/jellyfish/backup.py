"""Zone config backup/restore.

Writing zone config is the single most destructive thing this integration can
do to the controller: it resets every zone's run state to off and, if the
port mapping is wrong, can re-trigger the hardware fault on a faulty run.
This keeps a short rolling history of zone configs so a bad write can be
undone, rather than relying on the user having a copy somewhere.
"""

from __future__ import annotations

import time
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "jellyfish_zone_backup"
MAX_BACKUPS = 5


class ZoneConfigBackupEntry(TypedDict):
    saved_at: float
    zones: dict[str, Any]


class ZoneConfigBackup:
    """A per-config-entry rolling history of zone configs, newest first."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[list[ZoneConfigBackupEntry]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry_id}"
        )

    async def snapshot(self, zones: dict[str, Any]) -> None:
        """Save `zones` as the newest backup, before it's about to be overwritten."""
        if not zones:
            return
        history = await self._store.async_load() or []
        history.insert(0, {"saved_at": time.time(), "zones": zones})
        await self._store.async_save(history[:MAX_BACKUPS])

    async def history(self) -> list[ZoneConfigBackupEntry]:
        return await self._store.async_load() or []

    async def at(self, index: int) -> ZoneConfigBackupEntry | None:
        history = await self.history()
        return history[index] if 0 <= index < len(history) else None
