"""Tests for the integration entry setup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.we_are_home import (
    async_reload_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.we_are_home.const import (
    DOMAIN,
    PLATFORMS,
    SERVICE_GET_PROFILE,
    SERVICE_LIST_RULES,
    SERVICE_START,
    SERVICE_STOP,
    SERVICE_TRAIN,
)


async def test_async_setup(hass):
    """Legacy YAML setup initialises the domain namespace."""
    assert await async_setup(hass, {}) is True
    assert hass.data[DOMAIN] == {}


async def test_async_setup_entry(hass, monkeypatch):
    """A config entry wires coordinator, platform, and services."""
    entry = MockConfigEntry(domain=DOMAIN, data={"entities": ["light.a"]})
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    monkeypatch.setattr(
        "custom_components.we_are_home.coordinator.WeAreHomeCoordinator",
        MagicMock(return_value=coordinator),
    )
    forward = AsyncMock()
    monkeypatch.setattr(
        hass.config_entries, "async_forward_entry_setups", forward
    )

    assert await async_setup_entry(hass, entry) is True
    assert hass.data[DOMAIN][entry.entry_id]["coordinator"] is coordinator
    coordinator.async_config_entry_first_refresh.assert_awaited_once()
    forward.assert_awaited_once_with(entry, PLATFORMS)
    for service in (
        SERVICE_START,
        SERVICE_STOP,
        SERVICE_TRAIN,
        SERVICE_GET_PROFILE,
        SERVICE_LIST_RULES,
    ):
        assert hass.services.has_service(DOMAIN, service)


async def test_async_unload_entry(hass):
    """Unloading pops the entry and shuts down the coordinator."""
    entry = MockConfigEntry(domain=DOMAIN, data={"entities": ["light.a"]})
    entry.add_to_hass(hass)
    coordinator = SimpleNamespace(async_shutdown=AsyncMock())
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    assert await async_unload_entry(hass, entry) is True
    assert entry.entry_id not in hass.data[DOMAIN]
    coordinator.async_shutdown.assert_awaited_once()


async def test_async_unload_entry_without_coordinator(hass):
    """Unloading an entry without a coordinator still succeeds."""
    entry = MockConfigEntry(domain=DOMAIN, data={"entities": ["light.a"]})
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}

    assert await async_unload_entry(hass, entry) is True


async def test_async_reload_entry(hass, monkeypatch):
    """Reloading delegates to config entry reload."""
    entry = MockConfigEntry(domain=DOMAIN, data={"entities": ["light.a"]})
    entry.add_to_hass(hass)
    reload_mock = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reload_mock)

    await async_reload_entry(hass, entry)
    reload_mock.assert_awaited_once_with(entry.entry_id)
