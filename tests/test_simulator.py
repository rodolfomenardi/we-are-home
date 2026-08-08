"""Tests for the simulation engine and boost manager."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.core import State
from homeassistant.exceptions import ServiceNotFound

from custom_components.we_are_home.const import (
    DOMAIN,
    EVENT_COMMAND,
    EVENT_SEQUENCE_TRIGGERED,
    SLOTS_PER_DAY,
)
from custom_components.we_are_home.simulator import (
    BoostManager,
    SimulationEngine,
    _capture_entity_states,
    _restore_entity_states,
    _time_slot_index,
)

ENTITIES = ["light.sala", "switch.tv"]


def make_entry(**data) -> MockConfigEntry:
    """Build a config entry with the given data overrides."""
    defaults = {
        "entities": ENTITIES,
        "learning_interval": 60,
        "simulation_interval": 30,
        "restore_states": True,
        "min_confidence": 0.3,
        "boost_factor": 2.0,
    }
    defaults.update(data)
    return MockConfigEntry(domain=DOMAIN, data=defaults)


def make_hass(states: dict[str, str] | None = None) -> MagicMock:
    """Build a mock hass with state/service/bus doubles."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    # EventBus.async_fire is synchronous in real HA — use a plain mock
    hass.bus.async_fire = MagicMock()

    def _get(entity_id: str):
        if states is None:
            return None
        state = states.get(entity_id)
        return State(entity_id, state) if state is not None else None

    hass.states.get = MagicMock(side_effect=_get)
    return hass


def make_engine(
    hass: MagicMock,
    entry: MockConfigEntry,
    profiles: dict | None = None,
    rules: list[dict] | None = None,
) -> tuple[SimulationEngine, SimpleNamespace]:
    """Build engine + coordinator mock with profiles and rules."""
    coordinator = SimpleNamespace(
        _profiles=profiles or {},
        _sequence_rules=rules or [],
        hass=hass,
    )
    engine = SimulationEngine(hass, entry, coordinator)
    return engine, coordinator


def profile_dict(p_on: float = 0.5, confidence: float = 0.8) -> dict:
    """Serialised profiles for both day groups (weekday/weekend)."""
    base = {
        "entity_id": "light.sala",
        "confidence": confidence,
        "total_observations": 100,
        "slots": [
            {"slot_index": i, "p_on": p_on, "sample_count": 1}
            for i in range(SLOTS_PER_DAY)
        ],
    }
    return [
        {**base, "day_group": "weekday"},
        {**base, "day_group": "weekend"},
    ]


# ---------------------------------------------------------------------------
# Time helper
# ---------------------------------------------------------------------------


def test_time_slot_index():
    """Datetimes map to 15-min slot indices."""
    assert _time_slot_index(datetime(2026, 8, 3, 0, 0)) == 0
    assert _time_slot_index(datetime(2026, 8, 3, 12, 0)) == 48
    assert _time_slot_index(datetime(2026, 8, 3, 23, 59)) == 95


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


async def test_start_no_entities_warns_and_skips():
    """Starting without entities must not activate the engine."""
    hass = make_hass()
    entry = make_entry(entities=[])
    engine, _ = make_engine(hass, entry)
    await engine.start()
    assert not engine.active
    assert engine.started_at is None


async def test_start_captures_states():
    """Start captures pre-simulation states and activates."""
    hass = make_hass({"light.sala": "on", "switch.tv": "off"})
    engine, _ = make_engine(hass, make_entry())
    await engine.start()
    assert engine.active
    assert engine.started_at is not None
    assert engine._pre_simulation_states == {  # noqa: SLF001
        "light.sala": "on",
        "switch.tv": "off",
    }
    assert engine.commands_sent == 0


async def test_start_missing_states_default_to_off():
    """Entities without a current state are captured as off."""
    hass = make_hass({"light.sala": "on"})
    engine, _ = make_engine(hass, make_entry())
    await engine.start()
    assert engine._pre_simulation_states == {  # noqa: SLF001
        "light.sala": "on",
        "switch.tv": "off",
    }


async def test_stop_restores_states():
    """Stop restores entities to their pre-simulation states."""
    hass = make_hass({"light.sala": "on", "switch.tv": "off"})
    engine, _ = make_engine(hass, make_entry())
    await engine.start()
    await engine.stop()
    assert not engine.active
    assert engine._pre_simulation_states == {}  # noqa: SLF001
    # light.sala was on → TURN_ON; switch.tv was off → TURN_OFF
    calls = [c.args[:2] for c in hass.services.async_call.call_args_list]
    assert ("light", SERVICE_TURN_ON) in calls
    assert ("switch", SERVICE_TURN_OFF) in calls


async def test_stop_without_restore():
    """restore_states=false skips restoration calls."""
    hass = make_hass({"light.sala": "on"})
    engine, _ = make_engine(hass, make_entry(restore_states=False))
    await engine.start()
    await engine.stop()
    assert hass.services.async_call.call_count == 0


async def test_stop_with_no_captured_states():
    """Stopping with nothing captured is a no-op."""
    hass = make_hass()
    engine, _ = make_engine(hass, make_entry())
    engine._pre_simulation_states = {}  # noqa: SLF001
    await engine.stop()
    assert hass.services.async_call.call_count == 0


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------


async def test_tick_inactive_returns_zero():
    """An inactive engine never sends commands."""
    hass = make_hass()
    engine, _ = make_engine(hass, make_entry())
    assert await engine.tick() == 0


async def test_tick_no_profiles():
    """Entities without profiles are skipped."""
    hass = make_hass({"light.sala": "off"})
    engine, _ = make_engine(hass, make_entry())
    await engine.start()
    assert await engine.tick() == 0


async def test_tick_skips_below_confidence():
    """Profiles below the confidence threshold are skipped."""
    hass = make_hass({"light.sala": "off"})
    profiles = {"light.sala": profile_dict(p_on=1.0, confidence=0.1)}
    engine, _ = make_engine(hass, make_entry(min_confidence=0.3), profiles)
    await engine.start()
    assert await engine.tick() == 0


async def test_tick_turns_on_entity():
    """p_on=1.0 with entity off sends a TURN_ON command."""
    hass = make_hass({"light.sala": "off"})
    profiles = {"light.sala": profile_dict(p_on=1.0)}
    engine, _ = make_engine(hass, make_entry(), profiles)
    await engine.start()
    count = await engine.tick()
    assert count == 1
    assert engine.commands_sent == 1
    hass.services.async_call.assert_awaited_with(
        "light", SERVICE_TURN_ON, {"entity_id": "light.sala"}, blocking=False
    )


async def test_tick_turns_off_entity():
    """p_on=0.0 with entity on sends a TURN_OFF command."""
    hass = make_hass({"light.sala": "on"})
    profiles = {"light.sala": profile_dict(p_on=0.0)}
    engine, _ = make_engine(hass, make_entry(), profiles)
    await engine.start()
    count = await engine.tick()
    assert count == 1
    hass.services.async_call.assert_awaited_with(
        "light", SERVICE_TURN_OFF, {"entity_id": "light.sala"}, blocking=False
    )


async def test_tick_respects_grace_period():
    """Entities in the grace period are skipped."""
    hass = make_hass({"light.sala": "on"})
    profiles = {"light.sala": profile_dict(p_on=0.0)}
    engine, _ = make_engine(hass, make_entry(), profiles)
    await engine.start()
    engine._grace_period["light.sala"] = datetime.now()  # noqa: SLF001
    assert await engine.tick() == 0


async def test_tick_handles_unavailable_state_as_off():
    """An unavailable entity is treated as off (may turn on)."""
    hass = make_hass({"light.sala": "unavailable"})
    profiles = {"light.sala": profile_dict(p_on=1.0)}
    engine, _ = make_engine(hass, make_entry(), profiles)
    await engine.start()
    assert await engine.tick() == 1


async def test_tick_fires_command_events():
    """Each sent command fires a we_are_home_command event."""
    hass = make_hass({"light.sala": "off"})
    profiles = {"light.sala": profile_dict(p_on=1.0)}
    engine, _ = make_engine(hass, make_entry(), profiles)
    await engine.start()
    await engine.tick()
    hass.bus.async_fire.assert_called_with(
        EVENT_COMMAND,
        {
            "entity_id": "light.sala",
            "service": "light.turn_on",
            "reason": "simulation_tick",
        },
    )


# ---------------------------------------------------------------------------
# _send_command / grace period
# ---------------------------------------------------------------------------


async def test_send_command_marks_grace_period():
    """Sending a command marks the entity for conflict detection."""
    hass = make_hass()
    engine, _ = make_engine(hass, make_entry())
    await engine._send_command("light.sala", SERVICE_TURN_ON)  # noqa: SLF001
    assert "light.sala" in engine._grace_period  # noqa: SLF001


async def test_send_command_swallows_service_errors():
    """ServiceNotFound is logged and the event still fires."""
    hass = make_hass()
    hass.services.async_call.side_effect = ServiceNotFound("light", "turn_on")
    engine, _ = make_engine(hass, make_entry())
    await engine._send_command("light.sala", SERVICE_TURN_ON)  # noqa: SLF001
    hass.bus.async_fire.assert_called_once()


def test_in_grace_period():
    """Grace period logic honours the simulation interval."""
    hass = make_hass()
    engine, _ = make_engine(hass, make_entry())
    now = datetime.now()
    assert not engine._in_grace_period("light.sala", now)  # noqa: SLF001
    engine._grace_period["light.sala"] = now  # noqa: SLF001
    assert engine._in_grace_period("light.sala", now + timedelta(seconds=10))  # noqa: SLF001
    assert not engine._in_grace_period(  # noqa: SLF001
        "light.sala", now + timedelta(seconds=45)
    )


# ---------------------------------------------------------------------------
# BoostManager
# ---------------------------------------------------------------------------


def rule_dict(
    rule_id: str = "r1",
    source: str = "light.sala",
    source_state: str = "on",
    target: str = "switch.tv",
    confidence: float = 0.9,
) -> dict:
    """Serialised rule dict."""
    return {
        "id": rule_id,
        "source_entity": source,
        "source_state": source_state,
        "target_entity": target,
        "target_state": "on",
        "mean_delay": 120.0,
        "std_delay": 30.0,
        "occurrence_count": 10,
        "confidence": confidence,
        "boost_factor": 2.0,
        "discovery_window": 60,
        "last_observed": None,
    }


def test_boost_manager_trigger_no_rules():
    """No rules means no boosts."""
    manager = BoostManager()
    manager.trigger("light.sala", "on", {}, 2.0, SimpleNamespace(_sequence_rules=[]))
    assert manager.active_boosts == []


def test_boost_manager_trigger_matching_rule():
    """A matching rule creates a boost and fires the sequence event."""
    hass = make_hass()
    coordinator = SimpleNamespace(_sequence_rules=[rule_dict()], hass=hass)
    manager = BoostManager()
    manager.trigger("light.sala", "on", {}, 2.5, coordinator)
    assert len(manager._boosts) == 1  # noqa: SLF001
    boost = manager._boosts[0]  # noqa: SLF001
    assert boost.target_entity == "switch.tv"
    assert boost.peak_multiplier == 2.5
    hass.bus.async_fire.assert_called_once_with(
        EVENT_SEQUENCE_TRIGGERED,
        {
            "rule_id": "r1",
            "source": "light.sala",
            "target": "switch.tv",
            "mean_delay": 120.0,
            "boost_multiplier": 2.5,
        },
    )


def test_boost_manager_trigger_ignores_non_matching():
    """Rules for other entities/states are ignored."""
    hass = make_hass()
    coordinator = SimpleNamespace(
        _sequence_rules=[
            rule_dict(source="light.cozinha"),
            rule_dict(source_state="off"),
            rule_dict(confidence=0.1),
        ],
        hass=hass,
    )
    manager = BoostManager()
    manager.trigger("light.sala", "on", {}, 2.0, coordinator)
    assert manager._boosts == []  # noqa: SLF001
    assert hass.bus.async_fire.call_count == 0


def test_boost_manager_get_boost_none():
    """No boosts for an entity yields multiplier 1.0."""
    manager = BoostManager()
    assert manager.get_boost("switch.tv") == 1.0


def test_boost_manager_get_boost_active():
    """An active boost multiplies the probability."""
    hass = make_hass()
    coordinator = SimpleNamespace(_sequence_rules=[rule_dict()], hass=hass)
    manager = BoostManager()
    manager.trigger("light.sala", "on", {}, 2.0, coordinator)
    mult = manager.get_boost("switch.tv", datetime.now(UTC))
    assert mult > 1.0
    # unrelated entity unaffected
    assert manager.get_boost("light.cozinha", datetime.now(UTC)) == 1.0


def test_boost_manager_combined_capped_at_five():
    """Multiple boosts combine but cap at 5×."""
    activated = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    manager = BoostManager()
    manager._boosts = [  # noqa: SLF001
        SimpleNamespace(
            target_entity="switch.tv",
            peak_multiplier=2.0,
            activated_at=activated,
            mean_delay=60.0,
            std_delay=30.0,
            multiplier=2.0,
            expires_at=activated + timedelta(hours=1),
            current_multiplier=lambda at: 3.0,
        ),
        SimpleNamespace(
            target_entity="switch.tv",
            peak_multiplier=2.0,
            activated_at=activated,
            mean_delay=60.0,
            std_delay=30.0,
            multiplier=2.0,
            expires_at=activated + timedelta(hours=1),
            current_multiplier=lambda at: 3.0,
        ),
    ]
    assert manager.get_boost("switch.tv", activated) == 5.0  # 9 → capped


def test_boost_manager_expired_boosts_filtered():
    """Expired boosts disappear from active_boosts."""
    manager = BoostManager()
    expired = SimpleNamespace(is_expired=lambda at: True)
    fresh = SimpleNamespace(is_expired=lambda at: False)
    manager._boosts = [expired, fresh]  # noqa: SLF001
    assert manager.active_boosts == [fresh]


def test_boost_manager_clear():
    """clear removes all boosts."""
    hass = make_hass()
    coordinator = SimpleNamespace(_sequence_rules=[rule_dict()], hass=hass)
    manager = BoostManager()
    manager.trigger("light.sala", "on", {}, 2.0, coordinator)
    assert manager._boosts  # noqa: SLF001
    manager.clear()
    assert manager._boosts == []  # noqa: SLF001


# ---------------------------------------------------------------------------
# State capture / restore helpers
# ---------------------------------------------------------------------------


async def test_capture_entity_states():
    """Existing states are captured; missing default to off."""
    hass = make_hass({"light.sala": "on"})
    captured = await _capture_entity_states(hass, ENTITIES)
    assert captured == {"light.sala": "on", "switch.tv": "off"}


async def test_restore_entity_states():
    """On states trigger TURN_ON, off/unknown trigger TURN_OFF."""
    hass = make_hass()
    await _restore_entity_states(
        hass, {"light.sala": "on", "switch.tv": "off", "cover.x": "unknown"}
    )
    calls = [c.args[:2] for c in hass.services.async_call.call_args_list]
    assert ("light", SERVICE_TURN_ON) in calls
    assert ("switch", SERVICE_TURN_OFF) in calls
    assert ("cover", SERVICE_TURN_OFF) in calls


async def test_restore_entity_states_swallows_errors():
    """Service errors during restore are logged, not raised."""
    hass = make_hass()
    hass.services.async_call.side_effect = ServiceNotFound("light", "turn_on")
    await _restore_entity_states(hass, {"light.sala": "on"})
