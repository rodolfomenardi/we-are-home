"""Tests for the incremental learning engine."""

from datetime import datetime

import numpy as np
import pytest

from custom_components.we_are_home.const import (
    MATURITY_COLD,
    SLOTS_PER_DAY,
)
from custom_components.we_are_home.models.learner import (
    _day_of_week,
    _iso_to_datetime,
    _js_divergence,
    _slot_index,
    auto_detect_day_groups,
    build_time_profiles,
    discover_sequence_rules,
    incremental_update,
    normalize_day_group_labels,
)
from custom_components.we_are_home.models.sequence_rule import SequenceRule
from custom_components.we_are_home.models.time_profile import TimeProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_slot_index_boundaries():
    """Slot index maps 15-min windows across the day."""
    assert _slot_index(datetime(2026, 8, 3, 0, 0)) == 0
    assert _slot_index(datetime(2026, 8, 3, 0, 15)) == 1
    assert _slot_index(datetime(2026, 8, 3, 12, 0)) == 48
    assert _slot_index(datetime(2026, 8, 3, 23, 45)) == 95
    assert _slot_index(datetime(2026, 8, 3, 23, 59)) == 95  # clamped


def test_day_of_week():
    """2026-08-03 is a Monday."""
    assert _day_of_week(datetime(2026, 8, 3)) == 0
    assert _day_of_week(datetime(2026, 8, 8)) == 5  # Saturday
    assert _day_of_week(datetime(2026, 8, 9)) == 6  # Sunday


def test_iso_to_datetime():
    """Valid ISO strings parse; invalid return None."""
    parsed = _iso_to_datetime("2026-08-03T08:00:00")
    assert parsed == datetime(2026, 8, 3, 8, 0, 0)
    assert _iso_to_datetime("not-a-date") is None
    assert _iso_to_datetime(None) is None


def test_js_divergence_identical():
    """Identical distributions have JS divergence ≈ 0."""
    p = np.array([0.5, 0.5])
    assert _js_divergence(p, p) < 1e-6


def test_js_divergence_disjoint():
    """Disjoint point masses have JS divergence ≈ 1."""
    assert _js_divergence(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(1.0)


def test_js_divergence_partial_overlap():
    """Partially overlapping distributions land between 0 and 1."""
    p = np.array([0.9, 0.1])
    q = np.array([0.1, 0.9])
    js = _js_divergence(p, q)
    assert 0.0 < js < 1.0


# ---------------------------------------------------------------------------
# build_time_profiles
# ---------------------------------------------------------------------------


def _change(hour: int, minute: int, state: str, day: int = 3) -> dict:
    """Build a state change dict for a given hour/minute on 2026-08-{day}."""
    return {
        "last_changed": f"2026-08-{day:02d}T{hour:02d}:{minute:02d}:00",
        "state": state,
    }


def test_build_time_profiles_no_history():
    """Entities without history get 7 COLD zero-confidence profiles."""
    result = build_time_profiles({}, ["light.sala"])
    assert "light.sala" in result
    assert len(result["light.sala"]) == 7
    for profile in result["light.sala"]:
        assert profile.total_observations == 0
        assert profile.confidence == 0.0
        assert profile.maturity_level() == MATURITY_COLD


def test_build_time_profiles_populates_day_slots():
    """State changes populate the correct day-group slot."""
    history = {
        "light.sala": [
            _change(8, 0, "on"),   # Monday 08:00 → slot 32
            _change(8, 15, "off"),  # Monday 08:15 → slot 33
        ]
    }
    result = build_time_profiles(history, ["light.sala"])
    profiles = result["light.sala"]
    monday = profiles[0]  # 2026-08-03 is a Monday
    assert monday.slots[32].p_on == 1.0
    assert monday.slots[32].sample_count == 1
    # off observation lands in slot 33
    assert monday.slots[33].sample_count == 1
    assert monday.slots[33].p_on == 0.0
    # other days untouched
    assert profiles[1].total_observations == 0


def test_build_time_profiles_tracks_duration():
    """On/off pairs within the same slot compute duration."""
    history = {
        "light.sala": [
            _change(8, 0, "on"),
            _change(8, 14, "off"),
        ]
    }
    result = build_time_profiles(history, ["light.sala"])
    monday = result["light.sala"][0]
    assert monday.slots[32].mean_duration_on == pytest.approx(14.0)


def test_build_time_profiles_skips_invalid_timestamps():
    """Changes with unparsable timestamps are skipped."""
    history = {
        "light.sala": [
            {"last_changed": "garbage", "state": "on"},
            _change(9, 0, "on"),
        ]
    }
    result = build_time_profiles(history, ["light.sala"])
    total = sum(p.total_observations for p in result["light.sala"])
    assert total == 1


def test_build_time_profiles_recomputes_confidence():
    """Confidence is recomputed after all changes are applied."""
    history = {
        "light.sala": [
            _change(8, 0, "on"),
            _change(8, 15, "off"),
        ]
    }
    result = build_time_profiles(history, ["light.sala"])
    monday = result["light.sala"][0]
    assert monday.total_observations == 2
    assert monday.confidence > 0.0


# ---------------------------------------------------------------------------
# auto_detect_day_groups
# ---------------------------------------------------------------------------


def _profile_with_single_slot(entity: str, day: int, slot: int) -> TimeProfile:
    """Profile with one occupied slot for a single day."""
    profile = TimeProfile(entity_id=entity, day_group=str(day))
    profile.update_slot(slot, is_on=True)
    profile.recompute_confidence()
    return profile


def test_auto_detect_passthrough_when_not_seven():
    """Profiles with fewer than 7 days pass through unchanged."""
    profiles = [
        TimeProfile(entity_id="light.sala", day_group="weekday"),
        TimeProfile(entity_id="light.sala", day_group="weekend"),
    ]
    result = auto_detect_day_groups({"light.sala": profiles})
    assert result["light.sala"] == profiles


def test_auto_detect_merges_identical_days():
    """Identical daily patterns merge into canonical day-class profiles."""
    profiles = [
        _profile_with_single_slot("light.sala", day, 32) for day in range(7)
    ]
    result = auto_detect_day_groups({"light.sala": profiles})
    merged = result["light.sala"]
    # The pattern applies every day → both classes carry it
    assert {p.day_group for p in merged} == {"weekday", "weekend"}
    total = sum(p.total_observations for p in merged)
    assert total == 7


def test_auto_detect_weekday_weekend_split():
    """Distinct day patterns fall back to weekday/weekend groups."""
    profiles = [
        _profile_with_single_slot("light.sala", day, day * 10)
        for day in range(7)
    ]
    result = auto_detect_day_groups({"light.sala": profiles})
    groups = {p.day_group for p in result["light.sala"]}
    assert groups == {"weekday", "weekend"}
    total = sum(p.total_observations for p in result["light.sala"])
    assert total == 7


def test_auto_detect_preserves_total_observations():
    """Merging must not lose observations."""
    profiles = [
        _profile_with_single_slot("light.sala", day, 32) for day in range(7)
    ]
    result = auto_detect_day_groups({"light.sala": profiles})
    total = sum(p.total_observations for p in result["light.sala"])
    assert total == 7


def test_auto_detect_partial_merge_uses_canonical_labels():
    """Merged groups are labelled weekday/weekend, never numeric."""
    profiles = [
        _profile_with_single_slot("light.sala", d, 32)
        if d < 5
        else _profile_with_single_slot("light.sala", d, 80)
        for d in range(7)
    ]
    result = auto_detect_day_groups({"light.sala": profiles})
    groups = {p.day_group for p in result["light.sala"]}
    assert groups == {"weekday", "weekend"}
    by_name = {p.day_group: p for p in result["light.sala"]}
    # Each class keeps only its own days' data
    assert by_name["weekday"].slots[32].sample_count == 5
    assert by_name["weekday"].slots[80].sample_count == 0
    assert by_name["weekend"].slots[80].sample_count == 2


def test_normalize_day_group_labels_remaps_numeric():
    """Legacy numeric first-day labels become weekday/weekend."""
    weekday_like = TimeProfile(entity_id="light.sala", day_group="0")
    weekday_like.update_slot(32, is_on=True)
    weekend_like = TimeProfile(entity_id="light.sala", day_group="5")
    weekend_like.update_slot(80, is_on=True)
    normalized = normalize_day_group_labels([weekday_like, weekend_like])
    by_name = {p.day_group: p for p in normalized}
    assert set(by_name) == {"weekday", "weekend"}
    assert by_name["weekday"].slots[32].sample_count == 1
    assert by_name["weekend"].slots[80].sample_count == 1


def test_normalize_day_group_labels_merges_same_class():
    """Multiple numeric weekday groups merge into one canonical profile."""
    first = TimeProfile(entity_id="light.sala", day_group="0")
    first.update_slot(32, is_on=True)
    second = TimeProfile(entity_id="light.sala", day_group="2")
    second.update_slot(33, is_on=True)
    normalized = normalize_day_group_labels([first, second])
    assert len(normalized) == 1
    assert normalized[0].day_group == "weekday"
    assert normalized[0].total_observations == 2


def test_normalize_day_group_labels_passthrough():
    """Already-canonical labels pass through unchanged."""
    profile = TimeProfile(entity_id="light.sala", day_group="weekend")
    profile.update_slot(80, is_on=True)
    normalized = normalize_day_group_labels([profile])
    assert len(normalized) == 1
    assert normalized[0].day_group == "weekend"
    assert normalized[0].total_observations == 1


# ---------------------------------------------------------------------------
# discover_sequence_rules
# ---------------------------------------------------------------------------


def _sequence_day(date: int) -> list[tuple[str, int, int, str]]:
    """A day's worth of (entity, hour, minute, state) events.

    A turns on at 08:00, B at 08:01, A off at 08:05, B off at 08:06.
    """
    return [
        ("light.a", 8, 0, "on"),
        ("light.b", 8, 1, "on"),
        ("light.a", 8, 5, "off"),
        ("light.b", 8, 6, "off"),
    ]


def _sequence_history(days: int = 3) -> dict[str, list[dict]]:
    """Build history with the A/B pattern repeated over N days."""
    history: dict[str, list[dict]] = {"light.a": [], "light.b": []}
    for d in range(1, days + 1):
        for entity, hour, minute, state in _sequence_day(d):
            history[entity].append(
                _change(hour, minute, state, day=d)
            )
    return history


def test_discover_sequence_rules_requires_two_entities():
    """Fewer than 2 entities yields no rules."""
    assert discover_sequence_rules({}, ["light.a"]) == []


def test_discover_sequence_rules_finds_pairs():
    """A→B pairs within the window become rules."""
    rules = discover_sequence_rules(
        _sequence_history(days=3), ["light.a", "light.b"]
    )
    assert len(rules) >= 4
    ids = {r.id for r in rules}
    assert "light.a(on)→light.b(on)" in ids
    assert "light.a(off)→light.b(off)" in ids
    for rule in rules:
        assert rule.occurrence_count == 3
        assert rule.confidence >= 0.3


def test_discover_sequence_rules_skips_self_pairs():
    """Same-entity changes do not create rules."""
    history = {
        "light.a": [_change(8, 0, "on"), _change(8, 1, "off")],
    }
    rules = discover_sequence_rules(history, ["light.a"])
    assert rules == []


def test_discover_sequence_rules_respects_window():
    """Events beyond the window do not pair."""
    history = {
        "light.a": [_change(8, 0, "on")],
        "light.b": [_change(12, 0, "on")],  # 4h later
    }
    rules = discover_sequence_rules(
        history, ["light.a", "light.b"], window_minutes=60
    )
    assert rules == []


def test_discover_sequence_rules_min_occurrences():
    """Fewer than min_occurrences yields no rule."""
    rules = discover_sequence_rules(
        _sequence_history(days=2), ["light.a", "light.b"],
        min_occurrences=3,
    )
    assert rules == []


def test_discover_sequence_rules_skips_zero_delay():
    """Simultaneous events are ignored."""
    history = {
        "light.a": [{"last_changed": "2026-08-03T08:00:00", "state": "on"}],
        "light.b": [{"last_changed": "2026-08-03T08:00:00", "state": "on"}],
    }
    rules = discover_sequence_rules(history, ["light.a", "light.b"])
    assert rules == []


def test_discover_sequence_rules_sorted_by_confidence():
    """Rules are sorted by confidence descending."""
    rules = discover_sequence_rules(
        _sequence_history(days=3), ["light.a", "light.b"]
    )
    confidences = [r.confidence for r in rules]
    assert confidences == sorted(confidences, reverse=True)


def test_discover_sequence_rules_skips_invalid_timestamps():
    """Unparsable timestamps are skipped without crashing."""
    history = {
        "light.a": [{"last_changed": "garbage", "state": "on"}],
        "light.b": [{"last_changed": "2026-08-03T08:01:00", "state": "on"}],
    }
    rules = discover_sequence_rules(history, ["light.a", "light.b"])
    assert rules == []


# ---------------------------------------------------------------------------
# incremental_update
# ---------------------------------------------------------------------------


def test_incremental_update_new_entity_builds_profiles():
    """Entities without existing profiles are built from new history."""
    profiles: dict[str, list[TimeProfile]] = {}
    rules: list[SequenceRule] = []
    new_history = {
        "light.a": [_change(8, 0, "on"), _change(9, 0, "off")],
    }
    updated, updated_rules, obs, new_rules = incremental_update(
        profiles, rules, new_history, ["light.a"]
    )
    assert obs == 2
    assert "light.a" in updated
    assert len(updated["light.a"]) == 7
    assert new_rules == 0


def test_incremental_update_updates_existing_profile():
    """Existing profiles are updated with EMA via new observations."""
    profile = TimeProfile(entity_id="light.a", day_group="weekday")
    profile.update_slot(32, is_on=True)
    profile.recompute_confidence()
    profiles = {"light.a": [profile]}
    new_history = {
        "light.a": [_change(8, 0, "on")],  # Monday 08:00 → weekday slot 32
    }
    updated, _, obs, _ = incremental_update(
        profiles, [], new_history, ["light.a"]
    )
    assert obs == 1
    slot = updated["light.a"][0].slots[32]
    assert slot.sample_count == 2
    assert slot.p_on == pytest.approx(1.0)  # 0.7*1 + 0.3*1


def test_incremental_update_skips_entities_without_changes():
    """Entities with no new history are left untouched."""
    profile = TimeProfile(entity_id="light.a", day_group="weekday")
    profiles = {"light.a": [profile]}
    updated, _, obs, _ = incremental_update(
        profiles, [], {"light.b": [_change(8, 0, "on")]}, ["light.a"]
    )
    assert obs == 0
    assert updated["light.a"] == [profile]


def test_incremental_update_merges_new_rules():
    """Newly discovered rules are added to the existing set."""
    updated, rules, _, new_rules = incremental_update(
        {}, [], _sequence_history(days=3), ["light.a", "light.b"]
    )
    assert new_rules == len(rules)
    assert all(isinstance(r, SequenceRule) for r in rules)
    assert len(rules) >= 4


def test_incremental_update_updates_existing_rules():
    """Rules matching existing ids update their occurrences."""
    existing_rule = SequenceRule(
        id="light.a(on)→light.b(on)",
        source_entity="light.a",
        source_state="on",
        target_entity="light.b",
        target_state="on",
        mean_delay=60.0,
        occurrence_count=1,
    )
    updated, rules, _, new_rules = incremental_update(
        {},
        [existing_rule],
        _sequence_history(days=3),
        ["light.a", "light.b"],
    )
    assert new_rules == len(rules) - 1
    match = next(r for r in rules if r.id == existing_rule.id)
    assert match.occurrence_count > 1


def test_incremental_update_uses_real_delays():
    """Existing rules update with actual per-occurrence delays."""
    existing = SequenceRule(
        id="light.a(on)→light.b(on)",
        source_entity="light.a",
        source_state="on",
        target_entity="light.b",
        target_state="on",
        mean_delay=60.0,
        occurrence_count=3,
    )
    new_history = {
        "light.a": [_change(8, 0, "on", day=4), _change(8, 5, "on", day=5)],
        "light.b": [_change(8, 4, "on", day=4), _change(8, 9, "on", day=5)],
    }
    _, rules, _, _ = incremental_update(
        {}, [existing], new_history, ["light.a", "light.b"], 60
    )
    updated = next(r for r in rules if r.id == existing.id)
    # 3 initial + 2 real occurrences (never the mean repeated N times)
    assert updated.occurrence_count == 5
    # EMA(0.3): 60 → 114 → 151.8 as the two 240s delays are observed
    assert updated.mean_delay == pytest.approx(151.8)


def test_incremental_update_discovery_history_accumulates():
    """Once-daily patterns reach min_occurrences via wider history."""
    one_cycle = {
        "light.a": [_change(18, 0, "on", day=1)],
        "light.b": [_change(18, 2, "on", day=1)],
    }
    # A single cycle has 1 occurrence — below the threshold
    _, rules, _, new_count = incremental_update(
        {}, [], one_cycle, ["light.a", "light.b"], 60
    )
    assert new_count == 0
    assert rules == []

    # Accumulated history across 3 days crosses the threshold
    accumulated = dict(one_cycle)
    for day in (2, 3):
        accumulated["light.a"].append(_change(18, 0, "on", day=day))
        accumulated["light.b"].append(_change(18, 2, "on", day=day))
    _, rules2, _, new_count2 = incremental_update(
        {}, [], one_cycle, ["light.a", "light.b"], 60,
        discovery_history=accumulated,
    )
    assert new_count2 == 1
    rule = next(r for r in rules2 if r.id == "light.a(on)→light.b(on)")
    assert rule.occurrence_count == 3


def test_incremental_update_min_occurrences_passthrough(monkeypatch):
    """min_occurrences reaches the discovery call."""
    from custom_components.we_are_home.models import learner

    seen: dict[str, int] = {}

    def _fake_discover(history, entities, window, min_occ):
        seen["min_occ"] = min_occ
        return []

    monkeypatch.setattr(learner, "discover_sequence_rules", _fake_discover)
    incremental_update(
        {}, [], _sequence_history(days=3), ["light.a", "light.b"],
        60, min_occurrences=5,
    )
    assert seen["min_occ"] == 5
