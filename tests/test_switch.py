"""Tests for the presence simulation switch entity."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.we_are_home.const import DEFAULT_NAME, DOMAIN
from custom_components.we_are_home.switch import (
    PresenceSimulationSwitch,
    async_setup_entry,
)


class FakeSimulation:
    """Stand-in for SimulationEngine."""

    def __init__(self) -> None:
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.active = False
        self.active_boosts: list = []
        self.started_at: datetime | None = None
        self.commands_sent = 0


@pytest.fixture
def coordinator() -> SimpleNamespace:
    """A coordinator double with simulation and metric attributes."""
    return SimpleNamespace(
        config_entry=MockConfigEntry(
            domain=DOMAIN,
            data={
                "entities": ["light.sala", "switch.tv"],
                "name": "Casa",
            },
        ),
        simulation=FakeSimulation(),
        profiles_loaded=2,
        profiles_ready=1,
        sequence_rules_count=3,
        last_training=datetime(2026, 8, 1, 10, 0),
    )


def make_switch(hass, coordinator, entry_id="abc12345") -> PresenceSimulationSwitch:
    """Build a switch wired to hass for state writes."""
    switch = PresenceSimulationSwitch(coordinator, entry_id, DEFAULT_NAME)
    switch.hass = hass
    switch.entity_id = f"switch.we_are_home_{entry_id}"
    return switch


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def test_async_setup_entry_adds_switch(hass, coordinator):
    """A registered coordinator yields one switch entity."""
    entry = coordinator.config_entry
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}
    added: list = []
    # EntityPlatform passes a list to the callback
    await async_setup_entry(hass, entry, added.extend)
    assert len(added) == 1
    assert isinstance(added[0], PresenceSimulationSwitch)
    assert added[0].unique_id == f"{DOMAIN}_{entry.entry_id}"


async def test_async_setup_entry_missing_coordinator(hass, coordinator, caplog):
    """A missing coordinator logs an error and adds nothing."""
    entry = coordinator.config_entry
    hass.data.setdefault(DOMAIN, {})  # __init__.py normally guarantees this
    added: list = []
    await async_setup_entry(hass, entry, added.append)
    assert added == []
    assert "No coordinator found" in caplog.text


# ---------------------------------------------------------------------------
# Entity basics
# ---------------------------------------------------------------------------


def test_switch_defaults(coordinator):
    """The switch exposes its unique id and default icon."""
    switch = PresenceSimulationSwitch(coordinator, "abc12345", "Minha Casa")
    assert switch.unique_id == "we_are_home_abc12345"
    assert switch.name == "Minha Casa"
    assert switch.is_on is False
    assert switch.icon == "mdi:home-outline"
    assert switch.available is True


def test_icon_changes_when_on(coordinator):
    """The icon reflects the simulation state."""
    switch = PresenceSimulationSwitch(coordinator, "abc12345", DEFAULT_NAME)
    switch._attr_is_on = True  # noqa: SLF001
    assert switch.icon == "mdi:home-account"


def test_extra_state_attributes_no_simulation(coordinator):
    """Without an active simulation, attributes show defaults."""
    coordinator.simulation = None
    switch = PresenceSimulationSwitch(coordinator, "abc12345", DEFAULT_NAME)
    attrs = switch.extra_state_attributes
    assert attrs["entities_controlled"] == 2
    assert attrs["profiles_loaded"] == 2
    assert attrs["profiles_ready"] == 1
    assert attrs["sequence_rules"] == 3
    assert attrs["last_training"] == datetime(2026, 8, 1, 10, 0)
    assert attrs["active_boosts"] == 0
    assert attrs["simulation_uptime"] is None
    assert attrs["commands_sent"] == 0


def test_extra_state_attributes_with_simulation(coordinator):
    """An active simulation reports boosts, uptime, and commands."""
    coordinator.simulation.active_boosts = ["boost"]
    coordinator.simulation.started_at = datetime.now(UTC) - timedelta(hours=2)
    coordinator.simulation.commands_sent = 5
    switch = PresenceSimulationSwitch(coordinator, "abc12345", DEFAULT_NAME)
    attrs = switch.extra_state_attributes
    assert attrs["active_boosts"] == 1
    assert attrs["simulation_uptime"] == pytest.approx(2.0, abs=0.01)
    assert attrs["commands_sent"] == 5


# ---------------------------------------------------------------------------
# Toggling
# ---------------------------------------------------------------------------


async def test_turn_on_starts_simulation(hass, coordinator):
    """Turning on starts the engine and flips the state."""
    switch = make_switch(hass, coordinator)
    await switch.async_turn_on()
    assert switch.is_on is True
    coordinator.simulation.start.assert_awaited_once()
    assert coordinator.simulation.stop.call_count == 0


async def test_turn_off_stops_simulation(hass, coordinator):
    """Turning off stops the engine and flips the state."""
    switch = make_switch(hass, coordinator)
    switch._attr_is_on = True  # noqa: SLF001
    await switch.async_turn_off()
    assert switch.is_on is False
    coordinator.simulation.stop.assert_awaited_once()


async def test_turn_on_without_simulation(hass, coordinator):
    """Without an engine the switch stays off without crashing."""
    coordinator.simulation = None
    switch = PresenceSimulationSwitch(coordinator, "abc12345", DEFAULT_NAME)
    switch.hass = hass
    await switch.async_turn_on()
    assert switch.is_on is False
