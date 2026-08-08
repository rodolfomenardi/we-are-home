"""Tests for the SequenceRule and ActiveBoost models."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.we_are_home.models.sequence_rule import (
    ActiveBoost,
    SequenceRule,
)


def make_rule(**kwargs) -> SequenceRule:
    """Helper to build a rule with sensible defaults."""
    defaults = {
        "id": "light.a→light.b",
        "source_entity": "light.a",
        "source_state": "on",
        "target_entity": "light.b",
        "target_state": "on",
    }
    defaults.update(kwargs)
    return SequenceRule(**defaults)


# ---------------------------------------------------------------------------
# SequenceRule
# ---------------------------------------------------------------------------


def test_rule_defaults():
    """Defaults are sensible for a newly discovered rule."""
    rule = make_rule()
    assert rule.mean_delay == 0.0
    assert rule.std_delay == 0.0
    assert rule.occurrence_count == 1
    assert rule.confidence == 0.0
    assert rule.boost_factor == 2.0
    assert rule.discovery_window == 60
    assert rule.last_observed is None


def test_update_occurrence_zero_count_sets_directly():
    """First occurrence (count == 0) sets delay directly."""
    rule = make_rule(occurrence_count=0)
    rule.update_occurrence(delay_seconds=120.0)
    assert rule.mean_delay == 120.0
    assert rule.std_delay == 0.0
    assert rule.occurrence_count == 1
    assert rule.last_observed is not None


def test_update_occurrence_ema_blend():
    """Subsequent occurrences blend delays via EMA."""
    rule = make_rule(occurrence_count=0)
    rule.update_occurrence(delay_seconds=100.0)
    rule.update_occurrence(delay_seconds=200.0)
    # mean: 0.7*100 + 0.3*200 = 130
    assert rule.mean_delay == pytest.approx(130.0)
    # std: 0.7*0 + 0.3*|200-100| = 30
    assert rule.std_delay == pytest.approx(30.0)
    assert rule.occurrence_count == 2


def test_confidence_zero_below_three_occurrences():
    """Confidence stays 0 until 3 occurrences."""
    rule = make_rule(occurrence_count=2)
    rule._recompute_confidence()  # noqa: SLF001
    assert rule.confidence == 0.0


def test_confidence_with_three_occurrences():
    """3 occurrences with zero std delay yield stability-only confidence."""
    rule = make_rule()
    rule.occurrence_count = 3
    rule.mean_delay = 100.0
    rule.std_delay = 0.0
    rule._recompute_confidence()  # noqa: SLF001
    # count_score = log2(3/3)/4 = 0 → confidence = 0.4 * 1.0
    assert rule.confidence == pytest.approx(0.4)


def test_confidence_grows_with_occurrences():
    """Confidence increases with more occurrences."""
    low = make_rule()
    low.occurrence_count = 3
    low.mean_delay = 100.0
    low.std_delay = 0.0
    low._recompute_confidence()  # noqa: SLF001

    high = make_rule()
    high.occurrence_count = 30
    high.mean_delay = 100.0
    high.std_delay = 0.0
    high._recompute_confidence()  # noqa: SLF001

    assert high.confidence > low.confidence
    assert high.confidence <= 1.0


def test_confidence_drops_with_variability():
    """High delay variability lowers confidence."""
    stable = make_rule()
    stable.occurrence_count = 10
    stable.mean_delay = 100.0
    stable.std_delay = 0.0
    stable._recompute_confidence()  # noqa: SLF001

    unstable = make_rule()
    unstable.occurrence_count = 10
    unstable.mean_delay = 100.0
    unstable.std_delay = 90.0
    unstable._recompute_confidence()  # noqa: SLF001

    assert unstable.confidence < stable.confidence


def test_confidence_zero_mean_delay_no_division_error():
    """Zero mean delay must not divide by zero."""
    rule = make_rule()
    rule.occurrence_count = 5
    rule.mean_delay = 0.0
    rule.std_delay = 0.0
    rule._recompute_confidence()  # noqa: SLF001
    import math

    assert rule.confidence == pytest.approx(0.6 * (math.log2(5 / 3) / 4))


def test_to_dict_roundtrip():
    """to_dict/from_dict roundtrip preserves all fields."""
    rule = make_rule(
        mean_delay=42.5,
        std_delay=7.25,
        occurrence_count=8,
        confidence=0.66,
        boost_factor=3.0,
        discovery_window=45,
        last_observed=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    restored = SequenceRule.from_dict(rule.to_dict())
    assert restored.id == rule.id
    assert restored.source_entity == rule.source_entity
    assert restored.source_state == rule.source_state
    assert restored.target_entity == rule.target_entity
    assert restored.target_state == rule.target_state
    assert restored.mean_delay == pytest.approx(42.5)
    assert restored.std_delay == pytest.approx(7.25)
    assert restored.occurrence_count == 8
    assert restored.confidence == pytest.approx(0.66)
    assert restored.boost_factor == 3.0
    assert restored.discovery_window == 45
    assert restored.last_observed == rule.last_observed


def test_from_dict_missing_fields():
    """from_dict tolerates missing optional fields."""
    rule = SequenceRule.from_dict(
        {
            "id": "x→y",
            "source_entity": "x",
            "source_state": "on",
            "target_entity": "y",
            "target_state": "off",
        }
    )
    assert rule.mean_delay == 0.0
    assert rule.occurrence_count == 1
    assert rule.last_observed is None


def test_from_dict_no_last_observed():
    """from_dict handles null last_observed."""
    rule = SequenceRule.from_dict(
        {
            "id": "x→y",
            "source_entity": "x",
            "source_state": "on",
            "target_entity": "y",
            "target_state": "off",
            "last_observed": None,
        }
    )
    assert rule.last_observed is None


# ---------------------------------------------------------------------------
# ActiveBoost
# ---------------------------------------------------------------------------


def test_boost_expires_at():
    """expires_at = activated_at + mean_delay + 3*std_delay."""
    activated = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    boost = ActiveBoost(
        rule_id="r1",
        target_entity="light.b",
        activated_at=activated,
        mean_delay=120.0,
        std_delay=60.0,
    )
    expected = activated + timedelta(seconds=120 + 3 * 60)
    assert boost.expires_at == expected


def test_boost_peak_multiplier_at_activation():
    """At activation (or before), the multiplier is at its peak."""
    activated = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    boost = ActiveBoost(
        rule_id="r1",
        target_entity="light.b",
        peak_multiplier=3.0,
        activated_at=activated,
        mean_delay=120.0,
        std_delay=60.0,
    )
    assert boost.current_multiplier(activated) == 3.0
    assert boost.current_multiplier(activated - timedelta(seconds=5)) == 3.0


def test_boost_peak_at_mean_delay():
    """The Gaussian peaks exactly at mean_delay."""
    activated = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    boost = ActiveBoost(
        rule_id="r1",
        target_entity="light.b",
        peak_multiplier=2.0,
        activated_at=activated,
        mean_delay=120.0,
        std_delay=60.0,
    )
    at_peak = activated + timedelta(seconds=120)
    assert boost.current_multiplier(at_peak) == pytest.approx(2.0)


def test_boost_decays_between_activation_and_peak():
    """Multiplier is above 1.0 but below peak before mean_delay."""
    activated = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    boost = ActiveBoost(
        rule_id="r1",
        target_entity="light.b",
        peak_multiplier=2.0,
        activated_at=activated,
        mean_delay=120.0,
        std_delay=60.0,
    )
    mid = activated + timedelta(seconds=60)
    mult = boost.current_multiplier(mid)
    assert 1.0 < mult < 2.0


def test_boost_expired_returns_one():
    """After expiry the multiplier is 1.0 (no boost)."""
    activated = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    boost = ActiveBoost(
        rule_id="r1",
        target_entity="light.b",
        peak_multiplier=2.0,
        activated_at=activated,
        mean_delay=120.0,
        std_delay=60.0,
    )
    after = activated + timedelta(seconds=120 + 3 * 60 + 1)
    assert boost.current_multiplier(after) == 1.0
    assert boost.is_expired(after)


def test_boost_not_expired_at_activation():
    """A fresh boost is never expired."""
    activated = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    boost = ActiveBoost(
        rule_id="r1",
        target_entity="light.b",
        activated_at=activated,
        mean_delay=120.0,
        std_delay=60.0,
    )
    assert not boost.is_expired(activated)


def test_boost_handles_naive_datetime():
    """Naive datetimes (as produced by HA) are interpreted as UTC."""
    activated = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    boost = ActiveBoost(
        rule_id="r1",
        target_entity="light.b",
        activated_at=activated,
        mean_delay=120.0,
        std_delay=60.0,
    )
    naive = datetime(2026, 8, 1, 10, 0, 0)  # same instant, naive
    assert boost.current_multiplier(naive) == 2.0
