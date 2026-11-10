"""Device trigger tests: restart/disconnect/reconnect automation triggers."""

from __future__ import annotations

import asyncio

from pytest_homeassistant_custom_component.common import async_capture_events
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components import automation
from homeassistant.components.device_automation import (
    DeviceAutomationType,
    async_get_device_automations,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

from custom_components.jellyfish.const import DOMAIN

from .fake_controller import FakeController


async def _settle(hass: HomeAssistant, secs: float = 0.2) -> None:
    await asyncio.sleep(secs)
    await hass.async_block_till_done()


def _device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry.unique_id)})
    assert device is not None
    return device


async def test_only_controller_device_has_triggers(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    assert await async_setup_component(hass, "device_automation", {})
    controller = _device(hass, entry)
    registry = dr.async_get(hass)
    zone_device = registry.async_get_device(identifiers={(DOMAIN, f"{entry.unique_id}_Zone")})
    assert zone_device is not None

    result = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, [controller.id, zone_device.id]
    )
    # The controller device also picks up generic triggers from other platforms
    # (e.g. "connected"/"not_connected" from the connectivity binary_sensor) —
    # only check our own domain's triggers.
    ours = {t["type"] for t in result[controller.id] if t["domain"] == DOMAIN}
    assert ours == {"restarted", "disconnected", "reconnected"}
    assert all(t["domain"] != DOMAIN for t in result[zone_device.id])


async def _automations_for(
    hass: HomeAssistant, device_id: str, triggers: list[tuple[str, str]]
) -> None:
    """Set up one automation per (trigger_type, event_name) pair, in a single call.

    automation.DOMAIN only processes its config the first time it's set up, so
    multiple automations must be registered together, not via separate calls.
    """
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "trigger": [
                        {
                            "platform": "device",
                            "domain": DOMAIN,
                            "device_id": device_id,
                            "type": trigger_type,
                        }
                    ],
                    "action": {"event": event_name, "event_data": {}},
                }
                for trigger_type, event_name in triggers
            ]
        },
    )
    await hass.async_block_till_done()


async def test_restarted_trigger_fires(
    hass: HomeAssistant, entry: MockConfigEntry, fake: FakeController
) -> None:
    controller = _device(hass, entry)
    events = async_capture_events(hass, "test_restarted")
    await _automations_for(hass, controller.id, [("restarted", "test_restarted")])

    fake.reboot()
    await fake.drop_all()
    await _settle(hass, 2.0)

    assert len(events) == 1


async def test_disconnected_and_reconnected_triggers_fire(
    hass: HomeAssistant, entry: MockConfigEntry, fake: FakeController
) -> None:
    controller = _device(hass, entry)
    disconnected = async_capture_events(hass, "test_disconnected")
    reconnected = async_capture_events(hass, "test_reconnected")
    await _automations_for(
        hass,
        controller.id,
        [("disconnected", "test_disconnected"), ("reconnected", "test_reconnected")],
    )

    await fake.drop_all()
    await _settle(hass, 2.0)
    assert len(disconnected) == 1
    assert len(reconnected) == 1
