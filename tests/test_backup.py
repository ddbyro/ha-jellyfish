"""ZoneConfigBackup: storage key safety and basic round-trip."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.jellyfish.backup import ZoneConfigBackup


def test_malicious_unique_id_does_not_escape_storage_dir(hass: HomeAssistant) -> None:
    """A hostname-derived unique_id isn't restricted to a safe charset upstream,
    so the Store key built from it must not let a crafted value (e.g. containing
    path separators) write outside .storage/.
    """
    backup = ZoneConfigBackup(hass, "../../../../etc/passwd")
    storage_path = str(backup._store.path)  # noqa: SLF001
    assert ".." not in storage_path
    assert "/.storage/" in storage_path or storage_path.startswith(
        str(hass.config.path(".storage"))
    )


async def test_snapshot_and_history_round_trip(hass: HomeAssistant) -> None:
    backup = ZoneConfigBackup(hass, "jellyfish-a1b2")
    assert await backup.history() == []
    await backup.snapshot({"Zone": {"numPixels": 1}})
    history = await backup.history()
    assert len(history) == 1
    assert history[0]["zones"] == {"Zone": {"numPixels": 1}}
    assert await backup.at(0) == history[0]
    assert await backup.at(1) is None
