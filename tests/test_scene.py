"""Scene entities: one per (zone, saved pattern)."""

from __future__ import annotations

import asyncio
import json

from homeassistant.core import HomeAssistant

from custom_components.jellyfish.const import DOMAIN

from .fake_controller import FakeController


async def _settle(hass: HomeAssistant, secs: float = 0.2) -> None:
    await asyncio.sleep(secs)
    await hass.async_block_till_done()


def test_scenes_created_for_every_zone_and_pattern(hass: HomeAssistant, entry) -> None:
    # Fake controller starts with zones Zone/Garage and 3 saved patterns.
    for zone in ("zone", "garage"):
        for pattern in ("halloween_spookier01", "colors_orange", "mine_custom"):
            state = hass.states.get(f"scene.{zone}_{pattern}")
            assert state is not None, f"scene.{zone}_{pattern} missing"


async def test_activating_scene_runs_pattern(
    hass: HomeAssistant, entry, fake: FakeController
) -> None:
    await hass.services.async_call(
        "scene", "turn_on", {"entity_id": "scene.zone_colors_orange"}, blocking=True
    )
    await _settle(hass)
    sent = fake.sets("runPattern")[-1]["runPattern"]
    assert sent["file"] == "Colors/Orange"
    assert sent["zoneName"] == ["Zone"]


async def test_new_pattern_gets_a_new_scene(
    hass: HomeAssistant, entry, fake: FakeController
) -> None:
    eid = entry.entry_id
    assert hass.states.get("scene.zone_mine_redblue") is None
    await hass.services.async_call(
        DOMAIN, "save_pattern",
        {"config_entry_id": eid, "pattern": "Mine/RedBlue", "from_zone": "Zone"},
        blocking=True,
    )
    await _settle(hass, 0.4)
    assert hass.states.get("scene.zone_mine_redblue") is not None


async def test_deleted_pattern_scene_goes_unavailable(
    hass: HomeAssistant, entry, fake: FakeController
) -> None:
    eid = entry.entry_id
    assert hass.states.get("scene.zone_mine_custom").state != "unavailable"
    await hass.services.async_call(
        DOMAIN, "delete_pattern", {"config_entry_id": eid, "pattern": "Mine/Custom"},
        blocking=True,
    )
    await _settle(hass, 0.4)
    assert hass.states.get("scene.zone_mine_custom").state == "unavailable"
