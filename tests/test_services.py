"""Tests for the service handlers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.we_are_home import services, storage
from custom_components.we_are_home.const import (
    DOMAIN,
    SERVICE_GET_PROFILE,
    SERVICE_LIST_RULES,
    SERVICE_START,
    SERVICE_STOP,
    SERVICE_TRAIN,
)


class FakeSimulation:
    """Stand-in for SimulationEngine."""

    def __init__(self) -> None:
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self._pre_simulation_states: dict[str, str] = {"light.sala": "on"}
        self._entity_override = None
        self._restore_override = None


class FakeCoordinator:
    """Stand-in for WeAreHomeCoordinator."""

    def __init__(self, entry: MockConfigEntry) -> None:
        self.config_entry = entry
        self.simulation = FakeSimulation()
        self._profiles: dict = {}
        self._sequence_rules: list[dict] = []
        self.profiles_loaded = 0
        self.profiles_ready = 0
        self.sequence_rules_count = 0
        self.last_training = None

    def _get_simulation(self) -> FakeSimulation:
        return self.simulation


def make_entry(**data) -> MockConfigEntry:
    """Build a config entry with defaults."""
    defaults = {
        "entities": ["light.sala", "switch.tv"],
        "sequence_window": 60,
    }
    defaults.update(data)
    return MockConfigEntry(domain=DOMAIN, data=defaults)


@pytest.fixture
def fake_coordinator() -> FakeCoordinator:
    """A registered coordinator in hass.data."""
    entry = make_entry()
    coord = FakeCoordinator(entry)

    def _register(hass):
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
            "coordinator": coord
        }

    return coord, _register


def call(hass, service: str, **data) -> ServiceCall:
    """Build a ServiceCall (hass is the first positional arg in HA 2025)."""
    return ServiceCall(hass, DOMAIN, service, data)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_async_register_services(hass):
    """All five services are registered."""
    await services.async_register_services(hass)
    for service in (
        SERVICE_START,
        SERVICE_STOP,
        SERVICE_TRAIN,
        SERVICE_GET_PROFILE,
        SERVICE_LIST_RULES,
    ):
        assert hass.services.has_service(DOMAIN, service)


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


async def test_start_no_coordinator(hass):
    """Starting without an instance reports failure."""
    result = await services._handle_start(hass, call(hass, SERVICE_START))  # noqa: SLF001
    assert result == {"success": False, "error": "No configured instance found"}


async def test_start_success(hass, fake_coordinator):
    """Starting a configured instance activates its simulation."""
    coord, register = fake_coordinator
    register(hass)
    result = await services._handle_start(hass, call(hass, SERVICE_START))  # noqa: SLF001
    assert result["success"] is True
    assert result["instance_id"].startswith("switch.we_are_home_")
    coord.simulation.start.assert_awaited_once()


async def test_start_with_overrides(hass, fake_coordinator):
    """entity_id and restore_states overrides are applied."""
    coord, register = fake_coordinator
    register(hass)
    await services._handle_start(  # noqa: SLF001
        hass,
        call(
            hass,
            SERVICE_START,
            entity_id=["light.sala"],
            restore_states=False,
        ),
    )
    assert coord.simulation._entity_override == ["light.sala"]
    assert coord.simulation._restore_override is False


async def test_stop_no_coordinator(hass):
    """Stopping without an instance reports failure."""
    result = await services._handle_stop(hass, call(hass, SERVICE_STOP))  # noqa: SLF001
    assert result == {"success": False, "error": "No configured instance found"}


async def test_stop_success(hass, fake_coordinator):
    """Stopping restores captured states and reports the count."""
    coord, register = fake_coordinator
    register(hass)
    result = await services._handle_stop(hass, call(hass, SERVICE_STOP))  # noqa: SLF001
    assert result == {"success": True, "restored_entities": 1}
    coord.simulation.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# train
# ---------------------------------------------------------------------------


async def test_train_no_coordinator(hass):
    """Training without an instance reports failure."""
    result = await services._handle_train(hass, call(hass, SERVICE_TRAIN))  # noqa: SLF001
    assert result == {"success": False, "error": "No configured instance found"}


async def test_train_full_reset(hass, fake_coordinator, monkeypatch):
    """full_reset discards existing profiles and rebuilds."""
    coord, register = fake_coordinator
    register(hass)
    coord._profiles = {"light.sala": ["old"]}  # noqa: SLF001
    coord._sequence_rules = ["old-rule"]  # noqa: SLF001

    monkeypatch.setattr(
        "custom_components.we_are_home.history_reader.get_multi_entity_history",
        AsyncMock(return_value={}),
    )
    save_profile = AsyncMock()
    save_rules = AsyncMock()
    monkeypatch.setattr(storage, "save_profile", save_profile)
    monkeypatch.setattr(storage, "save_sequence_rules", save_rules)

    result = await services._handle_train(  # noqa: SLF001
        hass, call(hass, SERVICE_TRAIN, full_reset=True)
    )
    assert result["success"] is True
    assert result["entities_processed"] == 2
    # Empty history still builds COLD profiles for every configured entity
    assert set(coord._profiles) == {"light.sala", "switch.tv"}  # noqa: SLF001
    assert coord._sequence_rules == []  # noqa: SLF001
    assert coord.profiles_loaded == 2
    assert coord.profiles_ready == 2
    save_profile.assert_awaited()
    save_rules.assert_awaited()


async def test_train_incremental(hass, fake_coordinator, monkeypatch):
    """Training without reset updates existing profiles."""
    coord, register = fake_coordinator
    register(hass)

    from custom_components.we_are_home.models.time_profile import TimeProfile

    profile = TimeProfile(entity_id="light.sala", day_group="weekday")
    profile.update_slot(32, is_on=True)
    profile.recompute_confidence()
    coord._profiles = {"light.sala": [profile.to_dict()]}  # noqa: SLF001

    monkeypatch.setattr(
        "custom_components.we_are_home.history_reader.get_multi_entity_history",
        AsyncMock(
            return_value={
                "light.sala": [
                    {
                        "last_changed": "2026-08-03T08:00:00",  # Monday
                        "state": "on",
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(storage, "save_profile", AsyncMock())
    monkeypatch.setattr(storage, "save_sequence_rules", AsyncMock())

    result = await services._handle_train(hass, call(hass, SERVICE_TRAIN))  # noqa: SLF001
    assert result["success"] is True
    assert coord._profiles["light.sala"][0]["total_observations"] > 0  # noqa: SLF001


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


def _slots(peak_indices: list[int]) -> list[dict]:
    return [
        {
            "slot_index": i,
            "p_on": 1.0 if i in peak_indices else 0.0,
            "sample_count": 1 if i in peak_indices else 0,
        }
        for i in range(96)
    ]


async def test_get_profile_not_found(hass, monkeypatch):
    """Unknown entities report an error."""
    monkeypatch.setattr(storage, "load_profile", AsyncMock(return_value=None))
    result = await services._handle_get_profile(  # noqa: SLF001
        hass, call(hass, SERVICE_GET_PROFILE, entity_id="light.sala")
    )
    assert result == {"entity_id": "light.sala", "error": "No profile found"}


async def test_get_profile_summary(hass, monkeypatch):
    """Profile summaries include day groups and peak hours."""
    profile_data = {
        "entity_id": "light.sala",
        "profiles": [
            {
                "day_group": "weekday",
                "confidence": 0.6,
                "total_observations": 100,
                "slots": _slots([72, 73, 74]),  # 18:00-18:45
            },
            {
                "day_group": "weekend",
                "confidence": 0.2,
                "total_observations": 10,
                "slots": _slots([48]),
            },
        ],
    }
    monkeypatch.setattr(
        storage, "load_profile", AsyncMock(return_value=profile_data)
    )
    monkeypatch.setattr(
        storage,
        "load_sequence_rules",
        AsyncMock(
            return_value=[
                {
                    "id": "r1",
                    "source_entity": "light.sala",
                    "target_entity": "switch.tv",
                },
                {
                    "id": "r2",
                    "source_entity": "switch.tv",
                    "target_entity": "light.sala",
                },
            ]
        ),
    )

    result = await services._handle_get_profile(  # noqa: SLF001
        hass, call(hass, SERVICE_GET_PROFILE, entity_id="light.sala")
    )
    assert result["entity_id"] == "light.sala"
    assert result["domain"] == "light"
    assert result["confidence"] == 0.6
    assert result["total_observations"] == 110
    assert result["day_groups"]["weekday"]["peak_hours"] == ["18:00-18:45"]
    assert result["day_groups"]["weekend"]["avg_on_probability"] == pytest.approx(
        1 / 96, abs=0.001
    )
    assert result["sequence_rules_as_source"] == ["r1"]
    assert result["sequence_rules_as_target"] == ["r2"]


# ---------------------------------------------------------------------------
# list_rules
# ---------------------------------------------------------------------------


async def test_list_rules_all(hass, monkeypatch):
    """All rules are returned without filters."""
    monkeypatch.setattr(
        storage,
        "load_sequence_rules",
        AsyncMock(return_value=[{"id": "r1", "confidence": 0.9}]),
    )
    result = await services._handle_list_rules(hass, call(hass, SERVICE_LIST_RULES))  # noqa: SLF001
    assert result["total"] == 1
    assert result["rules"][0]["id"] == "r1"


async def test_list_rules_filters(hass, monkeypatch):
    """Rules are filtered by entity and minimum confidence."""
    rules = [
        {
            "id": "r1",
            "source_entity": "light.sala",
            "target_entity": "switch.tv",
            "mean_delay": 60.5,
            "std_delay": 5.25,
            "confidence": 0.9,
            "occurrence_count": 5,
        },
        {
            "id": "r2",
            "source_entity": "switch.tv",
            "target_entity": "cover.janela",
            "mean_delay": 120.0,
            "std_delay": 0.0,
            "confidence": 0.2,
            "occurrence_count": 2,
        },
    ]
    monkeypatch.setattr(storage, "load_sequence_rules", AsyncMock(return_value=rules))

    result = await services._handle_list_rules(  # noqa: SLF001
        hass, call(hass, SERVICE_LIST_RULES, entity_id="light.sala", min_confidence=0.5)
    )
    assert result["total"] == 1
    assert result["rules"][0] == {
        "id": "r1",
        "source": "light.sala",
        "target": "switch.tv",
        "mean_delay_seconds": 60.5,
        "std_delay_seconds": 5.2,
        "confidence": 0.9,
        "occurrences": 5,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def test_resolve_coordinator_no_data(hass):
    """No registered instances yields None."""
    assert services._resolve_coordinator(hass, None) is None  # noqa: SLF001


async def test_resolve_coordinator_default_first(hass):
    """Without switch_id the first coordinator is returned."""
    entry = make_entry()
    coord = FakeCoordinator(entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coord}
    assert services._resolve_coordinator(hass, None) is coord  # noqa: SLF001


async def test_resolve_coordinator_by_switch_id(hass):
    """switch_id matching an entry prefix resolves that coordinator."""
    entry = make_entry()
    coord = FakeCoordinator(entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coord}
    switch_id = f"switch.we_are_home_{entry.entry_id[:8]}"
    assert services._resolve_coordinator(hass, switch_id) is coord  # noqa: SLF001


async def test_resolve_coordinator_unknown_switch_id(hass):
    """Unknown switch ids yield None."""
    entry = make_entry()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": FakeCoordinator(entry)}
    assert services._resolve_coordinator(hass, "switch.other_12345678") is None  # noqa: SLF001


def test_compress_time_ranges_empty():
    assert services._compress_time_ranges([]) == []


def test_compress_time_ranges_single():
    assert services._compress_time_ranges(["18:00"]) == ["18:00-18:15"]


def test_compress_time_ranges_consecutive():
    times = ["18:00", "18:15", "18:30"]
    assert services._compress_time_ranges(times) == ["18:00-18:45"]


def test_compress_time_ranges_gap():
    times = ["18:00", "20:00"]
    assert services._compress_time_ranges(times) == ["18:00-18:15", "20:00-20:15"]


def test_compress_time_ranges_midnight_wrap():
    times = ["00:00", "23:45"]
    assert services._compress_time_ranges(times) == [
        "00:00-00:15",
        "23:45-00:00",
    ]


def test_next_slot():
    assert services._next_slot("18:00") == "18:15"
    assert services._next_slot("18:45") == "19:00"
    assert services._next_slot("23:45") == "00:00"
