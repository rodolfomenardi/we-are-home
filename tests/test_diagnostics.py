"""Tests for the diagnostics endpoint."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.we_are_home import diagnostics, history_reader, storage
from custom_components.we_are_home.const import DOMAIN


def make_entry(**data) -> MockConfigEntry:
    """Build a config entry with defaults."""
    defaults = {
        "entities": ["light.a", "switch.tv"],
        "learning_interval": 60,
        "simulation_interval": 30,
        "min_confidence": 0.3,
        "sequence_window": 60,
    }
    defaults.update(data)
    return MockConfigEntry(domain=DOMAIN, data=defaults)


def profile_dict(
    confidence: float = 0.9,
    observations: int = 5000,
    sample_count: int = 96,
) -> dict:
    """Serialised profile with maturity-level sample counts."""
    return {
        "entity_id": "light.a",
        "day_group": "weekday",
        "confidence": confidence,
        "total_observations": observations,
        "last_updated": "2026-08-01T10:00:00",
        "slots": [
            {
                "slot_index": i,
                "p_on": 0.5,
                "p_transition": 0.0,
                "mean_duration_on": 0.0,
                "std_duration_on": 0.0,
                "sample_count": sample_count if i < 90 else 0,
                "transition_count": 0,
                "duration_count": 0,
                "last_updated": None,
            }
            for i in range(96)
        ],
    }


@pytest.fixture
def patch_backend(monkeypatch):
    """Patch storage and history_reader used by diagnostics."""

    def _patch(
        profiles=None,
        rules=None,
        learning_log=None,
        recorder_info=None,
    ):
        monkeypatch.setattr(
            storage, "load_all_profiles", AsyncMock(return_value=profiles or {})
        )
        monkeypatch.setattr(
            storage, "load_sequence_rules", AsyncMock(return_value=rules or [])
        )
        monkeypatch.setattr(
            storage,
            "load_learning_log",
            AsyncMock(return_value=learning_log or []),
        )
        monkeypatch.setattr(
            history_reader,
            "get_recorder_info",
            AsyncMock(return_value=recorder_info or {"engine": "sqlite"}),
        )

    return _patch


async def test_diagnostics_full(hass, patch_backend):
    """All diagnostics sections are populated."""
    entry = make_entry()
    coordinator = SimpleNamespace(
        profiles_loaded=1,
        profiles_ready=1,
        sequence_rules_count=2,
        last_training=datetime(2026, 8, 1, 9, 0),
        simulation=SimpleNamespace(active=True),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    rules = [
        {
            "id": "r1",
            "source_entity": "light.a",
            "target_entity": "switch.tv",
            "occurrence_count": 10,
            "confidence": 0.9,
        },
        {
            "id": "r2",
            "source_entity": "switch.tv",
            "target_entity": "light.a",
            "occurrence_count": 2,
            "confidence": 0.2,
        },
    ]
    patch_backend(
        profiles={"light.a": {"entity_id": "light.a", "profiles": [profile_dict()]}},
        rules=rules,
        learning_log=[{"run": i} for i in range(15)],
        recorder_info={"engine": "sqlite", "backlog": 0},
    )

    data = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    assert data["config"]["entities"] == ["light.a", "switch.tv"]
    assert data["config"]["learning_interval"] == 60

    summary = data["profiles_summary"]
    assert summary["total_entities"] == 1
    assert summary["ready_entities"] == 1
    detail = summary["entities"]["light.a"]
    assert detail["confidence"] == 0.9
    assert detail["maturity"] == "STABLE"  # 5000 observations / 96 slots
    assert detail["total_observations"] == 5000
    assert detail["slots_with_data"] == 90
    assert detail["last_updated"] == "2026-08-01T10:00:00"

    rules_summary = data["sequence_rules"]
    assert rules_summary["total"] == 2
    assert rules_summary["avg_confidence"] == 0.55
    assert rules_summary["by_source"] == {"light.a": 1, "switch.tv": 1}
    assert rules_summary["most_frequent"][0]["id"] == "r1"

    assert len(data["learning_log"]) == 10  # truncated to last 10
    assert data["recorder"] == {"engine": "sqlite", "backlog": 0}

    coord = data["coordinator"]
    assert coord["profiles_loaded"] == 1
    assert coord["profiles_ready"] == 1
    assert coord["sequence_rules_count"] == 2
    assert coord["simulation_active"] is True


async def test_diagnostics_without_coordinator(hass, patch_backend):
    """Missing coordinator omits the coordinator section."""
    entry = make_entry()
    patch_backend(
        profiles={
            "light.a": {
                "entity_id": "light.a",
                "profiles": [
                    profile_dict(confidence=0.1, observations=10, sample_count=2)
                ],
            }
        }
    )
    data = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert "coordinator" not in data
    detail = data["profiles_summary"]["entities"]["light.a"]
    assert detail["maturity"] == "COLD"
    assert detail["confidence"] == 0.1


async def test_diagnostics_legacy_flat_profile(hass, patch_backend):
    """A stored profile dict without a profiles key yields zeros."""
    entry = make_entry()
    patch_backend(profiles={"light.a": profile_dict()})
    data = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    detail = data["profiles_summary"]["entities"]["light.a"]
    # Not nested in "profiles": the wrapper key is missing → no profiles
    assert detail["total_observations"] == 0
    assert detail["last_updated"] is None
