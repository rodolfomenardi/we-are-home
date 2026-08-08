"""Tests for the TimeProfile and TimeSlot data models."""

from datetime import datetime

import pytest

from custom_components.we_are_home.const import (
    MATURITY_COLD,
    MATURITY_HOT,
    MATURITY_STABLE,
    MATURITY_WARM,
    SLOTS_PER_DAY,
)
from custom_components.we_are_home.models.time_profile import (
    TimeProfile,
    TimeSlot,
)


def test_timeslot_defaults():
    """TimeSlot initialises with zeroed statistics."""
    slot = TimeSlot(slot_index=5)
    assert slot.slot_index == 5
    assert slot.p_on == 0.0
    assert slot.p_transition == 0.0
    assert slot.mean_duration_on == 0.0
    assert slot.std_duration_on == 0.0
    assert slot.sample_count == 0
    assert slot.last_updated is None


def test_timeprofile_initialises_96_slots():
    """TimeProfile creates 96 slots on initialisation."""
    profile = TimeProfile(entity_id="light.sala")
    assert len(profile.slots) == SLOTS_PER_DAY
    assert profile.slots[0].slot_index == 0
    assert profile.slots[95].slot_index == 95
    assert profile.day_group == "weekday"
    assert profile.confidence == 0.0
    assert profile.total_observations == 0


def test_update_slot_first_observation_sets_directly():
    """First observation sets p_on directly instead of EMA blending."""
    profile = TimeProfile(entity_id="light.sala")
    profile.update_slot(0, is_on=True, duration_on=10.0)
    slot = profile.slots[0]
    assert slot.p_on == 1.0
    assert slot.mean_duration_on == 10.0
    assert slot.std_duration_on == 0.0
    assert slot.sample_count == 1
    assert slot.last_updated is not None


def test_update_slot_ema_blends_subsequent_observations():
    """Subsequent observations blend via EMA with default alpha 0.3."""
    profile = TimeProfile(entity_id="light.sala")
    profile.update_slot(0, is_on=True, duration_on=10.0)
    profile.update_slot(0, is_on=True, duration_on=20.0)
    slot = profile.slots[0]
    # p_on: 0.7*1.0 + 0.3*1.0 = 1.0
    assert slot.p_on == pytest.approx(1.0)
    # mean duration: 0.7*10 + 0.3*20 = 13
    assert slot.mean_duration_on == pytest.approx(13.0)
    # std: 0.7*0 + 0.3*|20-10| = 3
    assert slot.std_duration_on == pytest.approx(3.0)
    assert slot.sample_count == 2


def test_update_slot_off_observation():
    """An off observation lowers p_on via EMA."""
    profile = TimeProfile(entity_id="light.sala")
    profile.update_slot(0, is_on=True)
    profile.update_slot(0, is_on=False)
    assert profile.slots[0].p_on == pytest.approx(0.7)


def test_update_slot_invalid_index_ignored():
    """Out-of-range slot indices are silently ignored."""
    profile = TimeProfile(entity_id="light.sala")
    profile.update_slot(-1, is_on=True)
    profile.update_slot(SLOTS_PER_DAY, is_on=True)
    assert all(s.sample_count == 0 for s in profile.slots)


def test_update_slot_custom_alpha():
    """A custom alpha is honoured."""
    profile = TimeProfile(entity_id="light.sala")
    profile.update_slot(0, is_on=True, alpha=0.5)
    profile.update_slot(0, is_on=False, alpha=0.5)
    assert profile.slots[0].p_on == pytest.approx(0.5)


def test_update_p_transition():
    """Transition probability updates with EMA."""
    profile = TimeProfile(entity_id="light.sala")
    profile.update_p_transition(10, transitioned=True)
    assert profile.slots[10].p_transition == 1.0
    profile.update_p_transition(10, transitioned=False)
    assert profile.slots[10].p_transition == pytest.approx(0.7)
    assert profile.slots[10].transition_count == 2


def test_update_p_transition_invalid_index_ignored():
    """Out-of-range slot indices are silently ignored."""
    profile = TimeProfile(entity_id="light.sala")
    profile.update_p_transition(100, transitioned=True)
    profile.update_p_transition(-3, transitioned=True)
    assert all(s.p_transition == 0.0 for s in profile.slots)


def test_recompute_confidence_zero_samples():
    """No samples means zero confidence."""
    profile = TimeProfile(entity_id="light.sala")
    assert profile.recompute_confidence() == 0.0
    assert profile.total_observations == 0


def test_recompute_confidence_with_samples():
    """Confidence grows with sample count and slot coverage."""
    profile = TimeProfile(entity_id="light.sala")
    # 3 samples in every slot: 288 total, full coverage
    for i in range(SLOTS_PER_DAY):
        for _ in range(3):
            profile.update_slot(i, is_on=True)
    confidence = profile.recompute_confidence()
    assert profile.total_observations == 288
    assert confidence > 0.0
    assert confidence <= 1.0
    # Expect: sample_confidence = log2(3)/6, coverage = 1.0
    import math

    expected = 0.7 * (math.log2(3) / 6.0) + 0.3 * 1.0
    assert confidence == pytest.approx(expected)


def test_recompute_confidence_weights_partial_coverage():
    """Partial coverage contributes only 30% weight."""
    profile = TimeProfile(entity_id="light.sala")
    for _ in range(3):
        profile.update_slot(0, is_on=True)
    confidence = profile.recompute_confidence()
    # sample_confidence = 0 (avg < 1), coverage = 1/96
    assert confidence == pytest.approx(0.3 * (1 / SLOTS_PER_DAY))


def test_maturity_level_boundaries():
    """Maturity level thresholds: 3 / 14 / 30 average observations."""
    profile = TimeProfile(entity_id="light.sala")
    assert profile.maturity_level() == MATURITY_COLD

    # avg 1 sample per slot → COLD
    for i in range(SLOTS_PER_DAY):
        profile.update_slot(i, is_on=True)
    profile.recompute_confidence()
    assert profile.maturity_level() == MATURITY_COLD

    # avg 4 per slot → WARM
    for i in range(SLOTS_PER_DAY):
        for _ in range(3):
            profile.update_slot(i, is_on=True)
    profile.recompute_confidence()
    assert profile.maturity_level() == MATURITY_WARM

    # avg 15 per slot → HOT
    for i in range(SLOTS_PER_DAY):
        for _ in range(11):
            profile.update_slot(i, is_on=True)
    profile.recompute_confidence()
    assert profile.maturity_level() == MATURITY_HOT

    # avg 30 per slot → STABLE
    for i in range(SLOTS_PER_DAY):
        for _ in range(15):
            profile.update_slot(i, is_on=True)
    profile.recompute_confidence()
    assert profile.maturity_level() == MATURITY_STABLE


def test_to_dict_roundtrip():
    """to_dict/from_dict roundtrip preserves all data."""
    profile = TimeProfile(entity_id="light.sala", day_group="weekend")
    profile.update_slot(0, is_on=True, duration_on=12.0)
    profile.update_slot(1, is_on=False)
    profile.update_p_transition(2, transitioned=True)
    profile.last_updated = datetime(2026, 8, 1, 10, 30, 0)
    profile.recompute_confidence()

    data = profile.to_dict()
    restored = TimeProfile.from_dict(data)

    assert restored.entity_id == "light.sala"
    assert restored.day_group == "weekend"
    assert restored.confidence == pytest.approx(profile.confidence)
    assert restored.total_observations == profile.total_observations
    assert restored.last_updated == profile.last_updated
    assert len(restored.slots) == SLOTS_PER_DAY
    assert restored.slots[0].p_on == pytest.approx(1.0)
    assert restored.slots[0].mean_duration_on == pytest.approx(12.0)
    assert restored.slots[0].sample_count == 1
    assert restored.slots[1].p_on == pytest.approx(0.0)
    assert restored.slots[2].p_transition == pytest.approx(1.0)


def test_from_dict_missing_fields():
    """from_dict tolerates missing optional fields."""
    profile = TimeProfile.from_dict(
        {"entity_id": "switch.tv", "slots": [{"slot_index": 0}]}
    )
    assert profile.entity_id == "switch.tv"
    assert profile.day_group == "weekday"
    assert len(profile.slots) == 1
    assert profile.slots[0].p_on == 0.0
    assert profile.slots[0].sample_count == 0
    assert profile.last_updated is None


def test_from_dict_no_slots():
    """from_dict without slots yields an empty slots list."""
    profile = TimeProfile.from_dict({"entity_id": "light.sala"})
    assert profile.slots == []
