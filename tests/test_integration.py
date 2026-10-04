"""End-to-end tests against the fake controller."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_EFFECT, ATTR_RGB_COLOR
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.jellyfish.const import DOMAIN
from custom_components.jellyfish.diagnostics import async_get_config_entry_diagnostics

from .fake_controller import FakeController


async def _settle(hass: HomeAssistant, secs: float = 0.2) -> None:
    await asyncio.sleep(secs)
    await hass.async_block_till_done()


async def _sets(hass: HomeAssistant, fake: FakeController, key: str) -> list[dict]:
    """Messages the fake received, after letting in-flight frames arrive."""
    await _settle(hass)
    return fake.sets(key)


async def _last_run(hass: HomeAssistant, fake: FakeController) -> dict:
    rp = (await _sets(hass, fake, "runPattern"))[-1]["runPattern"]
    return {**rp, "data": json.loads(rp["data"]) if rp["data"] else None}


async def test_setup_creates_entities(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    zone = hass.states.get("light.zone")
    assert zone.state == "on"
    assert zone.attributes[ATTR_EFFECT] == "Halloween/Spookier01"
    assert zone.attributes["pattern_type"] == "Chase"
    assert hass.states.get("light.garage").state == "off"
    assert hass.states.get("light.home_all_zones").state == "on"
    assert hass.states.get("select.zone_pattern").state == "Halloween/Spookier01"
    assert hass.states.get("number.zone_speed").state == "0"
    assert hass.states.get("sensor.zone_ports").state == "LED3 0-79, LED1 0-56"
    assert hass.states.get("sensor.zone_pixels").state == "137"
    assert hass.states.get("sensor.home_firmware").state == "4.6.1"
    assert hass.states.get("binary_sensor.home_connected").state == "on"
    assert hass.states.get("sensor.home_daily_schedule_events").state == "1"
    assert hass.states.get("text.home_controller_name").state == "Home"


async def test_turn_off_and_push(hass: HomeAssistant, entry, fake: FakeController) -> None:
    await hass.services.async_call("light", "turn_off", {"entity_id": "light.zone"}, blocking=True)
    await _settle(hass)
    assert (await _last_run(hass, fake))["state"] == 0
    assert hass.states.get("light.zone").state == "off"


async def test_turn_on_effect(hass: HomeAssistant, entry, fake: FakeController) -> None:
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.garage", ATTR_EFFECT: "Colors/Orange"},
        blocking=True,
    )
    await _settle(hass)
    run = (await _last_run(hass, fake))
    assert run["file"] == "Colors/Orange" and run["zoneName"] == ["Garage"]
    assert hass.states.get("light.garage").attributes[ATTR_EFFECT] == "Colors/Orange"


async def test_turn_on_rgb_and_brightness(hass: HomeAssistant, entry, fake) -> None:
    await hass.services.async_call(
        "light", "turn_on",
        {"entity_id": "light.zone", ATTR_RGB_COLOR: (10, 20, 30), ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    await _settle(hass)
    data = (await _last_run(hass, fake))["data"]
    assert data["type"] == "Color" and data["colors"] == [10, 20, 30]
    assert data["runData"]["brightness"] == 50
    # Every required field is present or the controller rejects the command.
    for key in ("spaceBetweenPixels", "effectBetweenPixels", "skip", "numOfLeds", "direction"):
        assert key in data
    state = hass.states.get("light.zone")
    assert state.attributes[ATTR_RGB_COLOR] == (10, 20, 30)


async def test_brightness_only_keeps_pattern(hass: HomeAssistant, entry, fake) -> None:
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.zone", ATTR_BRIGHTNESS: 51}, blocking=True
    )
    data = (await _last_run(hass, fake))["data"]
    assert data["type"] == "Chase" and data["runData"]["brightness"] == 20


async def test_change_from_app_is_pushed(hass: HomeAssistant, entry, fake) -> None:
    """A second client (the phone app) changes the lights; HA follows instantly."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"http://127.0.0.1:{fake.port}/ws") as ws:
            await ws.send_str(json.dumps({"cmd": "toCtlrSet", "runPattern": {
                "file": "Colors/Orange", "data": "", "id": "", "state": 1,
                "zoneName": ["Garage"]}}))
            await ws.receive()
    await _settle(hass)
    assert hass.states.get("light.garage").state == "on"
    assert hass.states.get("select.garage_pattern").state == "Colors/Orange"


async def test_select_and_number(hass: HomeAssistant, entry, fake) -> None:
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.zone_pattern", "option": "Colors/Orange"}, blocking=True,
    )
    assert (await _last_run(hass, fake))["file"] == "Colors/Orange"
    await _settle(hass)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.zone_speed", "value": 42}, blocking=True
    )
    assert (await _last_run(hass, fake))["data"]["runData"]["speed"] == 42
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.zone_direction", "option": "Right"}, blocking=True,
    )
    assert (await _last_run(hass, fake))["data"]["direction"] == "Right"


async def test_custom_pattern_service(hass: HomeAssistant, entry, fake) -> None:
    await hass.services.async_call(
        DOMAIN, "run_custom_pattern",
        {"entity_id": "light.zone", "type": "Chase", "colors": [[255, 0, 0], [0, 0, 255]],
         "speed": 5, "save_as": "Mine/RedBlue"},
        blocking=True,
    )
    data = (await _last_run(hass, fake))["data"]
    assert data["colors"] == [255, 0, 0, 0, 0, 255] and data["runData"]["speed"] == 5
    assert (await _sets(hass, fake, "patternFileData"))[-1]["patternFileData"]["name"] == "RedBlue"
    await _settle(hass, 0.4)
    assert "Mine/RedBlue" in hass.states.get("light.zone").attributes["effect_list"]


async def test_pattern_services(hass: HomeAssistant, entry, fake) -> None:
    eid = entry.entry_id
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "delete_pattern",
            {"config_entry_id": eid, "pattern": "Halloween/Spookier01"}, blocking=True,
        )
    await hass.services.async_call(
        DOMAIN, "delete_pattern", {"config_entry_id": eid, "pattern": "Mine/Custom"},
        blocking=True,
    )
    assert (await _sets(hass, fake, "patternFileDelete"))
    resp = await hass.services.async_call(
        DOMAIN, "get_pattern", {"config_entry_id": eid, "pattern": "Colors/Orange"},
        blocking=True, return_response=True,
    )
    assert resp["data"]["colors"] == [255, 80, 0]
    await hass.services.async_call(
        DOMAIN, "save_pattern",
        {"config_entry_id": eid, "pattern": "Mine/Copy", "from_zone": "Zone", "speed": 9},
        blocking=True,
    )
    saved = json.loads((await _sets(hass, fake, "patternFileData"))[-1]["patternFileData"]["jsonData"])
    assert saved["type"] == "Chase" and saved["runData"]["speed"] == 9


async def test_schedule_services(hass: HomeAssistant, entry, fake) -> None:
    eid = entry.entry_id
    resp = await hass.services.async_call(
        DOMAIN, "get_schedule", {"config_entry_id": eid}, blocking=True, return_response=True
    )
    assert resp["daily"][0]["actions"][0]["startFrom"] == "sunset"
    assert resp["calendar"] == []
    events = [{"days": ["F", "SA"], "actions": [
        {"type": "RUN", "startFrom": "time", "hour": 19, "minute": 30,
         "patternFile": "Colors/Orange", "zones": ["Zone"]},
        {"type": "STOP", "startFrom": "time", "hour": 23, "minute": 0, "zones": ["Zone"]}]}]
    await hass.services.async_call(
        DOMAIN, "set_schedule", {"config_entry_id": eid, "kind": "daily", "events": events},
        blocking=True,
    )
    await _settle(hass)
    assert fake.state["daily"][0]["days"] == ["F", "SA"]
    attrs = hass.states.get("sensor.home_daily_schedule_events").attributes
    assert attrs["events"][0]["actions"][0]["hour"] == 19
    with pytest.raises(ServiceValidationError):
        bad = [{"days": ["M"], "actions": [{**events[0]["actions"][0], "patternFile": "Nope/X"}]}]
        await hass.services.async_call(
            DOMAIN, "set_schedule", {"config_entry_id": eid, "kind": "daily", "events": bad},
            blocking=True,
        )


async def test_zone_config_requires_confirm(hass: HomeAssistant, entry, fake) -> None:
    eid = entry.entry_id
    zones = {"Zone": {"portMap": [{"phyPort": 3, "phyStartIdx": 0, "phyEndIdx": 79},
                                  {"phyPort": 1, "phyStartIdx": 0, "phyEndIdx": 56}]}}
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_zone_config", {"config_entry_id": eid, "zones": zones, "confirm": False},
            blocking=True,
        )
    assert not (await _sets(hass, fake, "zones"))
    await hass.services.async_call(
        DOMAIN, "set_zone_config", {"config_entry_id": eid, "zones": zones, "confirm": True},
        blocking=True,
    )
    sent = (await _sets(hass, fake, "zones"))[-1]["zones"]["Zone"]
    assert sent["numPixels"] == 137
    assert sent["portMap"][1]["zoneRGBStartIdx"] == 80
    assert sent["portMap"][0]["ctlrName"] == "JellyFish-2AB3.local"


async def test_restart_detection(hass: HomeAssistant, entry, fake) -> None:
    fake.reboot()
    await fake.drop_all()
    await _settle(hass, 2.0)
    assert hass.states.get("binary_sensor.home_connected").state == "on"
    assert hass.states.get("sensor.home_connection_drops").state == "1"
    assert hass.states.get("sensor.home_restarts_detected").state == "1"
    assert hass.states.get("light.zone").state == "off"


async def test_diagnostics_redacts(hass: HomeAssistant, entry) -> None:
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["controller"]["time_config"]["lat"] == "**REDACTED**"
    assert diag["connection"]["connected"] is True
    assert "Zone" in diag["controller"]["zones"]
