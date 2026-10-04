"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from custom_components.jellyfish.const import DOMAIN

from .fake_controller import FakeController


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def fake(socket_enabled) -> AsyncGenerator[FakeController]:
    controller = FakeController()
    await controller.start()
    yield controller
    await controller.stop()


@pytest.fixture
async def entry(hass: HomeAssistant, fake: FakeController) -> AsyncGenerator[MockConfigEntry]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="jellyfish-2ab3",
        title="Home",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: fake.port},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
