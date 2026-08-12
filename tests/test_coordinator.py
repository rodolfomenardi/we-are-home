"""Tests for the WeAreHomeCoordinator."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.we_are_home import history_reader, storage
from custom_components.we_are_home.const import DOMAIN
from custom_components.we_are_home.coordinator import WeAreHomeCoordinator

ENTITIES = ["light.a", "light.b"]


def make_entry(**data) -> MockConfigEntry:
    """Build a config entry with defaults."""
    defaults = {
        "entities": ENTITIES,
        "learning_interval": 60,
        "min_confidence": 0.3,
        "sequence_window": 60,
    }
    defaults.update(data)
    return MockConfigEntry(domain=DOMAIN, data=defaults)


def profile_dict(confidence: float = 0.9, day_group: str = "weekday") -> dict:
    """Serialised profile for storage/coordinator tests."""
    return {
        "entity_id": "light.a",
        "day_group": day_group,
        "confidence": confidence,
        "total_observations": 100,
        "last_updated": None,
        "slots": [
            {
                "slot_index": i,
                "p_on": 0.5,
                "p_transition": 0.0,
                "mean_duration_on": 0.0,
                "std_duration_on": 0.0,
                "sample_count": 1 if i == 32 else 0,
                "transition_count": 0,
                "duration_count": 0,
                "last_updated": None,
            }
            for i in range(96)
        ],
    }


def rule_dict() -> dict:
    """Serialised sequence rule."""
    return {
        "id": "light.a(on)→light.b(on)",
        "source_entity": "light.a",
        "source_state": "on",
        "target_entity": "light.b",
        "target_state": "on",
        "mean_delay": 120.0,
        "std_delay": 30.0,
        "occurrence_count": 3,
        "confidence": 0.4,
        "boost_factor": 2.0,
        "discovery_window": 60,
        "last_observed": None,
    }


def three_day_history() -> dict[str, list[dict]]:
    """Three identical weekdays of A→B pair activity (Mon-Wed)."""
    days = ["2026-08-03", "2026-08-04", "2026-08-05"]
    history: dict[str, list[dict]] = {"light.a": [], "light.b": []}
    for day in days:
        history["light.a"].extend(
            [
                {"last_changed": f"{day}T18:00:00", "state": "on"},
                {"last_changed": f"{day}T18:30:00", "state": "off"},
            ]
        )
        history["light.b"].extend(
            [
                {"last_changed": f"{day}T18:02:00", "state": "on"},
                {"last_changed": f"{day}T18:32:00", "state": "off"},
            ]
        )
    return history


@pytest.fixture
def patch_storage(monkeypatch):
    """Patch all storage functions used by the coordinator."""

    def _patch(**overrides):
        defaults = {
            "load_all_profiles": AsyncMock(return_value={}),
            "load_sequence_rules": AsyncMock(return_value=[]),
            "save_profile": AsyncMock(),
            "save_sequence_rules": AsyncMock(),
            "delete_profile": AsyncMock(),
            "append_learning_run": AsyncMock(),
        }
        defaults.update(overrides)
        for name, mock in defaults.items():
            monkeypatch.setattr(storage, name, mock)
        return defaults

    return _patch


@pytest.fixture
def no_recent_changes(monkeypatch):
    """Recent state changes come back empty (no new history)."""
    monkeypatch.setattr(
        history_reader, "get_recent_state_changes", AsyncMock(return_value={})
    )
    return monkeypatch


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


async def test_init_update_interval_is_timedelta(hass):
    """The coordinator converts the minute interval to a timedelta.

    DataUpdateCoordinator calls value.total_seconds() on update_interval,
    so an int here would crash at instantiation.
    """
    coord = WeAreHomeCoordinator(hass, make_entry(learning_interval=45))
    assert coord.update_interval == timedelta(minutes=45)


async def test_init_default_learning_interval(hass):
    """Missing learning_interval falls back to the default."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"entities": ["light.a"], "min_confidence": 0.3}
    )
    coord = WeAreHomeCoordinator(hass, entry)
    assert coord.update_interval == timedelta(minutes=60)


async def test_async_update_data_no_entities(hass):
    """An entry without entities updates nothing."""
    coord = WeAreHomeCoordinator(hass, make_entry(entities=[]))
    assert await coord._async_update_data() == {  # noqa: SLF001
        "profiles_loaded": 0,
        "profiles_ready": 0,
    }


# ---------------------------------------------------------------------------
# Stored path
# ---------------------------------------------------------------------------


async def test_async_update_data_loads_stored_profiles(
    hass, patch_storage, no_recent_changes
):
    """Stored profiles are loaded and unwrapped from their wrapper."""
    patch_storage(
        load_all_profiles=AsyncMock(
            return_value={"light.a": {"entity_id": "light.a", "profiles": [profile_dict()]}}
        ),
        load_sequence_rules=AsyncMock(return_value=[rule_dict()]),
    )
    coord = WeAreHomeCoordinator(hass, make_entry())
    result = await coord._async_update_data()  # noqa: SLF001

    # light.a loaded from storage + light.b bootstrapped (no history → COLD)
    assert result["profiles_loaded"] == 2
    assert result["profiles_ready"] == 1
    assert result["sequence_rules"] == 1
    assert result["last_learning"] is not None
    # Wrapper unwrapped: values are lists of profile dicts, not wrappers
    assert isinstance(coord._profiles["light.a"], list)  # noqa: SLF001
    assert coord._profiles["light.a"][0]["confidence"] == 0.9  # noqa: SLF001
    assert "light.b" in coord._profiles  # noqa: SLF001 — bootstrapped
    assert coord.profiles_ready == 1
    assert coord.sequence_rules_count == 1


async def test_async_update_data_stored_below_confidence(
    hass, patch_storage, no_recent_changes
):
    """Stored profiles below min_confidence are not counted as ready."""
    patch_storage(
        load_all_profiles=AsyncMock(
            return_value={
                "light.a": {
                    "entity_id": "light.a",
                    "profiles": [profile_dict(confidence=0.1)],
                }
            }
        ),
        load_sequence_rules=AsyncMock(return_value=[]),
    )
    coord = WeAreHomeCoordinator(hass, make_entry())
    result = await coord._async_update_data()  # noqa: SLF001
    assert result["profiles_loaded"] == 2  # light.a from storage + light.b bootstrapped
    assert result["profiles_ready"] == 0


async def test_async_update_data_drops_stale_profiles(
    hass, patch_storage, no_recent_changes
):
    """Stored profiles for entities removed from config are dropped."""
    patched = patch_storage(
        load_all_profiles=AsyncMock(
            return_value={
                "light.a": {
                    "entity_id": "light.a",
                    "profiles": [profile_dict()],
                },
                "light.removed": {
                    "entity_id": "light.removed",
                    "profiles": [profile_dict()],
                },
            }
        ),
        load_sequence_rules=AsyncMock(
            return_value=[
                rule_dict(),
                {
                    "id": "light.a(on)→light.removed(on)",
                    "source_entity": "light.a",
                    "source_state": "on",
                    "target_entity": "light.removed",
                },
            ]
        ),
    )
    coord = WeAreHomeCoordinator(hass, make_entry())
    result = await coord._async_update_data()  # noqa: SLF001

    # light.removed is not in the config → dropped; light.b bootstrapped
    assert "light.removed" not in coord._profiles  # noqa: SLF001
    assert set(coord._profiles) == {"light.a", "light.b"}  # noqa: SLF001
    assert result["profiles_loaded"] == 2

    # Profile file purged from disk
    patched["delete_profile"].assert_awaited_once()
    assert patched["delete_profile"].await_args.args[1] == "light.removed"

    # Rule referencing the removed entity is dropped and persisted
    # (first save = purge; later saves come from the new-entity bootstrap)
    assert [r["id"] for r in coord._sequence_rules] == [  # noqa: SLF001
        "light.a(on)→light.b(on)"
    ]
    first_save = patched["save_sequence_rules"].await_args_list[0]
    kept = first_save.args[1]
    assert len(kept) == 1
    assert kept[0]["id"] == "light.a(on)→light.b(on)"


async def test_async_update_data_stored_legacy_flat_profile(
    hass, patch_storage, no_recent_changes
):
    """A stored dict without a profiles key is treated as one profile."""
    patch_storage(
        load_all_profiles=AsyncMock(
            return_value={"light.a": profile_dict()}
        ),
        load_sequence_rules=AsyncMock(return_value=[]),
    )
    coord = WeAreHomeCoordinator(hass, make_entry())
    result = await coord._async_update_data()  # noqa: SLF001
    assert result["profiles_loaded"] == 2  # light.a from storage + light.b bootstrapped
    assert result["profiles_ready"] == 1  # only light.a is ready; light.b COLD


# ---------------------------------------------------------------------------
# Fresh-build path
# ---------------------------------------------------------------------------


async def test_async_update_data_builds_fresh(hass, patch_storage, monkeypatch):
    """With no stored data, profiles and rules are built from history."""
    patched = patch_storage()
    monkeypatch.setattr(
        history_reader,
        "get_multi_entity_history",
        AsyncMock(return_value=three_day_history()),
    )
    monkeypatch.setattr(
        history_reader, "get_recent_state_changes", AsyncMock(return_value={})
    )

    coord = WeAreHomeCoordinator(hass, make_entry())
    result = await coord._async_update_data()  # noqa: SLF001

    assert result["profiles_loaded"] == 2
    assert set(coord._profiles) == {"light.a", "light.b"}  # noqa: SLF001
    # Identical days merge into one data group; empty days form another
    assert len(coord._profiles["light.a"]) == 2  # noqa: SLF001
    assert len(coord._sequence_rules) == 4  # noqa: SLF001
    rule_ids = {r["id"] for r in coord._sequence_rules}  # noqa: SLF001
    assert "light.a(on)→light.b(on)" in rule_ids
    assert patched["save_profile"].await_count == 2
    assert patched["save_sequence_rules"].await_count == 1


# ---------------------------------------------------------------------------
# Incremental path
# ---------------------------------------------------------------------------


async def test_async_update_data_incremental(hass, patch_storage, monkeypatch):
    """Existing profiles are updated with recent state changes."""
    patched = patch_storage()
    monkeypatch.setattr(
        history_reader,
        "get_recent_state_changes",
        AsyncMock(
            return_value={
                "light.a": [
                    {"last_changed": "2026-08-03T08:00:00", "state": "on"}
                ]
            }
        ),
    )

    coord = WeAreHomeCoordinator(hass, make_entry())
    coord._profiles = {"light.a": [profile_dict()]}  # noqa: SLF001
    coord._sequence_rules = [rule_dict()]  # noqa: SLF001

    result = await coord._async_update_data()  # noqa: SLF001

    assert result["profiles_loaded"] == 1
    # Confidence is recomputed from the actual data (2 samples → ~0.006),
    # so the profile is not "ready" against min_confidence.
    assert result["profiles_ready"] == 0
    # Slot 32 (08:00) gained one observation
    slots = coord._profiles["light.a"][0]["slots"]  # noqa: SLF001
    assert slots[32]["sample_count"] == 2
    assert patched["save_profile"].await_count == 1
    assert patched["append_learning_run"].await_count == 1
    assert coord._last_learning is not None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Errors / lifecycle
# ---------------------------------------------------------------------------


async def test_async_update_data_raises_update_failed(hass, monkeypatch):
    """History query failures surface as UpdateFailed."""
    monkeypatch.setattr(
        history_reader,
        "get_recent_state_changes",
        AsyncMock(side_effect=RuntimeError("recorder down")),
    )
    coord = WeAreHomeCoordinator(hass, make_entry())
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()  # noqa: SLF001


async def test_async_shutdown_stops_active_simulation(hass):
    """Shutdown stops an active simulation."""
    coord = WeAreHomeCoordinator(hass, make_entry())
    coord.simulation = SimpleNamespace(active=True, stop=AsyncMock())
    await coord.async_shutdown()
    coord.simulation.stop.assert_awaited_once()


async def test_async_shutdown_skips_inactive(hass):
    """Shutdown does not stop an inactive simulation."""
    coord = WeAreHomeCoordinator(hass, make_entry())
    coord.simulation = SimpleNamespace(active=False, stop=AsyncMock())
    await coord.async_shutdown()
    coord.simulation.stop.assert_not_awaited()


async def test_async_shutdown_without_simulation(hass):
    """Shutdown without a simulation engine is a no-op."""
    coord = WeAreHomeCoordinator(hass, make_entry())
    await coord.async_shutdown()


async def test_get_simulation_creates_once(hass):
    """_get_simulation lazily creates and reuses the engine."""
    coord = WeAreHomeCoordinator(hass, make_entry())
    sim = coord._get_simulation()  # noqa: SLF001
    assert sim is coord.simulation
    assert coord._get_simulation() is sim  # noqa: SLF001
