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
from homeassistant.util import slugify

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "jellyfish_zone_backup"
MAX_BACKUPS = 5


class ZoneConfigBackupEntry(TypedDict):
    saved_at: float
    zones: dict[str, Any]


class ZoneConfigBackup:
    """A rolling history of zone configs for one controller, newest first.

    Keyed by the config entry's unique_id (derived from the controller's
    self-reported hostname, stable across reconfigures), not entry_id —
    removing and re-adding the integration gets a new entry_id but the same
    unique_id, and the backup history should survive that.

    unique_id is only lowercased and has ".local" stripped (see config_flow's
    `_unique_id`), not actually restricted to a safe character set — the
    controller is a device on the LAN, not something we fully trust the
    content of. Slugify it again here before using it as a Store key, since
    `Store.path` is a bare `os.path.join(config_dir, ".storage", key)` with no
    sanitization of its own: an unslugified key could otherwise escape
    `.storage/` entirely.
    """

    def __init__(self, hass: HomeAssistant, unique_id: str) -> None:
        self._store: Store[list[ZoneConfigBackupEntry]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{slugify(unique_id)}"
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
