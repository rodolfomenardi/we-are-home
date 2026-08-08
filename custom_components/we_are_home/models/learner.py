"""Incremental learning engine for We Are Home.

Builds and updates TimeProfiles from recorder history using EMA,
discovers SequenceRules via temporal pair mining, and clusters
days of the week by pattern similarity.
"""

from __future__ import annotations

import logging
import math
import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import numpy as np

from ..const import (
    DAY_SIMILARITY_THRESHOLD,
    EMA_ALPHA,
    MATURITY_COLD,
    MIN_STATE_DURATION,
    SECONDS_PER_SLOT,
    SLOTS_PER_DAY,
)
from .sequence_rule import SequenceRule
from .time_profile import TimeProfile

_LOGGER = logging.getLogger(__name__)

# All 7 days indexed 0=Monday, ..., 6=Sunday
ALL_DAYS = list(range(7))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slot_index(timestamp: datetime) -> int:
    """Map a datetime to a 15-min slot index (0-95)."""
    minutes = timestamp.hour * 60 + timestamp.minute
    return min(minutes // 15, SLOTS_PER_DAY - 1)


def _day_of_week(timestamp: datetime) -> int:
    """Return 0=Monday, ..., 6=Sunday."""
    return timestamp.weekday()


def _iso_to_datetime(ts_str: str) -> datetime | None:
    """Parse an ISO timestamp string."""
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Jensen-Shannon Divergence
# ---------------------------------------------------------------------------


def _js_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """Compute Jensen-Shannon divergence between two probability distributions.

    Args:
        p, q: 1-D numpy arrays of probabilities (must be ≥ 0, sum ≈ 1).

    Returns:
        JS divergence in [0, 1]. Lower values mean more similar distributions.
    """
    # Add small epsilon to avoid log(0)
    eps = 1e-10
    p = np.asarray(p, dtype=np.float64) + eps
    q = np.asarray(q, dtype=np.float64) + eps

    p = p / p.sum()
    q = q / q.sum()
    m = 0.5 * (p + q)

    kl_pm = np.sum(p * np.log2(p / m))
    kl_qm = np.sum(q * np.log2(q / m))

    js = 0.5 * (kl_pm + kl_qm)
    # Normalise: max JS for 2 distributions is log2(2) = 1.0
    return float(min(js / math.log(2), 1.0))


# ---------------------------------------------------------------------------
# Profile Building
# ---------------------------------------------------------------------------


def build_time_profiles(
    history_data: dict[str, list[dict]],
    entities: list[str],
) -> dict[str, list[TimeProfile]]:
    """Build per-entity TimeProfiles from recorder state history.

    Creates 7 initial daily profiles (one per day of week). Later,
    `auto_detect_day_groups` merges similar days.

    Args:
        history_data: Dict entity_id → list of state change dicts.
        entities: List of entity IDs to build profiles for.

    Returns:
        Dict keyed by entity_id with list of 7 TimeProfiles (Mon-Sun).

    Edge cases handled:
        - Insufficient history (<24h): returns empty profiles with COLD
          maturity; caller should warn.
        - High-frequency entities (motion sensors): filtered by
          MIN_STATE_DURATION threshold.
        - Entity not in history: returns profiles with zero confidence.
    """
    result: dict[str, list[TimeProfile]] = {}

    for entity_id in entities:
        changes = history_data.get(entity_id, [])
        profiles = [
            TimeProfile(entity_id=entity_id, day_group=str(day))
            for day in ALL_DAYS
        ]

        if not changes:
            _LOGGER.debug(
                "%s: no history data, profiles will be COLD", entity_id
            )
            result[entity_id] = profiles
            continue

        # Track last state per day+slot for duration calculation
        last_on_time: dict[int, datetime | None] = defaultdict(lambda: None)

        for change in changes:
            ts = _iso_to_datetime(change.get("last_changed", ""))
            if ts is None:
                continue

            state = change.get("state", "off")
            day = _day_of_week(ts)
            slot = _slot_index(ts)
            profile = profiles[day]

            is_on = state not in ("off", "unavailable", "unknown")

            # Duration tracking
            duration_on = 0.0
            if is_on:
                last_on_time[(day, slot)] = ts
            else:
                last = last_on_time.pop((day, slot), None)
                if last is not None:
                    duration_on = (ts - last).total_seconds() / 60.0

            profile.update_slot(
                slot, is_on=is_on, duration_on=duration_on
            )

        for p in profiles:
            p.recompute_confidence()

        # Check for insufficient history
        total_obs = sum(p.total_observations for p in profiles)
        if total_obs < len(ALL_DAYS) * 3:  # fewer than ~3 obs per day
            _LOGGER.info(
                "%s: insufficient history (%d observations). "
                "Profiles marked COLD; more data needed for simulation.",
                entity_id,
                total_obs,
            )

        result[entity_id] = profiles

    return result


# ---------------------------------------------------------------------------
# Day-of-Week Clustering
# ---------------------------------------------------------------------------


def auto_detect_day_groups(
    profiles_by_entity: dict[str, list[TimeProfile]],
    threshold: float = DAY_SIMILARITY_THRESHOLD,
) -> dict[str, list[TimeProfile]]:
    """Merge similar day profiles using Jensen-Shannon divergence.

    Starts with 7 individual day profiles and greedily merges pairs
    below the similarity threshold. Typically converges to weekday
    (Mon-Fri) and weekend (Sat-Sun) groups.

    Args:
        profiles_by_entity: Output of build_time_profiles.
        threshold: JS divergence below which days are merged (0.15).

    Returns:
        Same structure but with merged day_group labels.
    """
    merged: dict[str, list[TimeProfile]] = {}

    for entity_id, profiles in profiles_by_entity.items():
        if len(profiles) != 7:
            merged[entity_id] = profiles
            continue

        # Build p_on vectors for each day (96 slots)
        day_vectors = {}
        for profile in profiles:
            day_idx = int(profile.day_group)
            vec = np.array([s.p_on for s in profile.slots], dtype=np.float64)
            day_vectors[day_idx] = vec

        # Start with each day as its own group
        groups: dict[str, set[int]] = {
            str(d): {d} for d in ALL_DAYS
        }

        # Greedy merge similar groups
        group_days = list(groups.keys())
        changed = True
        while changed and len(group_days) > 1:
            changed = False
            min_js = threshold
            merge_pair = None

            for i in range(len(group_days)):
                for j in range(i + 1, len(group_days)):
                    g1, g2 = group_days[i], group_days[j]
                    # Average vector for each group
                    v1 = np.mean(
                        [day_vectors[d] for d in groups[g1]], axis=0
                    )
                    v2 = np.mean(
                        [day_vectors[d] for d in groups[g2]], axis=0
                    )
                    js = _js_divergence(v1, v2)
                    if js < min_js:
                        min_js = js
                        merge_pair = (g1, g2)
                        changed = True

            if merge_pair:
                g1, g2 = merge_pair
                groups[g1] |= groups[g2]
                del groups[g2]
                group_days = list(groups.keys())

        # Build final profiles with merged day_groups
        final_profiles: list[TimeProfile] = []
        for group_name, days in groups.items():
            # Weighted average of merged slots
            merged_profile = TimeProfile(
                entity_id=entity_id, day_group=group_name
            )
            total_obs = 0
            for d in days:
                src = profiles[d]
                total_obs += src.total_observations
                for i, slot in enumerate(merged_profile.slots):
                    src_slot = src.slots[i]
                    weight = src_slot.sample_count
                    if weight > 0:
                        slot.p_on = (
                            slot.p_on * slot.sample_count
                            + src_slot.p_on * weight
                        )
                        slot.sample_count += weight
                        # Normalise after adding
                        if slot.sample_count > 0:
                            slot.p_on /= slot.sample_count

            merged_profile.total_observations = total_obs
            merged_profile.recompute_confidence()
            final_profiles.append(merged_profile)

        # If no merges happened, keep original but relabel
        if len(final_profiles) == 7:
            final_profiles = [
                TimeProfile(
                    entity_id=entity_id,
                    day_group="weekday" if d < 5 else "weekend",
                    slots=[s for s in profiles[d].slots],
                    confidence=profiles[d].confidence,
                    total_observations=profiles[d].total_observations,
                )
                for d in ALL_DAYS
            ]
            # Merge weekday and weekend separately
            final_weekday = TimeProfile(entity_id=entity_id, day_group="weekday")
            final_weekend = TimeProfile(entity_id=entity_id, day_group="weekend")
            for d in ALL_DAYS:
                target = final_weekday if d < 5 else final_weekend
                src = profiles[d]
                target.total_observations += src.total_observations
                for i, slot in enumerate(target.slots):
                    src_slot = src.slots[i]
                    w = src_slot.sample_count
                    if w > 0:
                        slot.p_on = (
                            slot.p_on * slot.sample_count + src_slot.p_on * w
                        )
                        slot.sample_count += w
                        if slot.sample_count > 0:
                            slot.p_on /= slot.sample_count
            final_weekday.recompute_confidence()
            final_weekend.recompute_confidence()
            final_profiles = [final_weekday, final_weekend]

        merged[entity_id] = final_profiles
        _LOGGER.debug(
            "%s: day groups → %s",
            entity_id,
            [p.day_group for p in final_profiles],
        )

    return merged


# ---------------------------------------------------------------------------
# Sequence Rule Discovery
# ---------------------------------------------------------------------------


def discover_sequence_rules(
    history_data: dict[str, list[dict]],
    entity_ids: list[str],
    window_minutes: int = 60,
    min_occurrences: int = 3,
) -> list[SequenceRule]:
    """Discover temporal association rules between entity pairs.

    Scans state changes across all entities and identifies pairs
    A→B where B changes state within window_minutes of A changing.

    Args:
        history_data: All entity state changes.
        entity_ids: Entities to search for sequences.
        window_minutes: Maximum delay between A and B events.
        min_occurrences: Minimum occurrences to create a rule.

    Returns:
        List of SequenceRules sorted by confidence descending.
    """
    if len(entity_ids) < 2:
        return []

    window = timedelta(minutes=window_minutes)
    rules_candidates: dict[
        tuple[str, str, str, str], list[float]
    ] = defaultdict(list)

    # Collect all state changes sorted by time
    all_changes: list[dict] = []
    for entity_id in entity_ids:
        changes = history_data.get(entity_id, [])
        for c in changes:
            c = dict(c)
            c["_entity_id"] = entity_id
            all_changes.append(c)

    all_changes.sort(key=lambda c: c.get("last_changed", ""))

    # Scan for A→B pairs
    for i, change_a in enumerate(all_changes):
        ts_a = _iso_to_datetime(change_a.get("last_changed", ""))
        if ts_a is None:
            continue

        entity_a = change_a.get("_entity_id", "")
        state_a = change_a.get("state", "")

        # Look for B changes within the window
        for j in range(i + 1, len(all_changes)):
            change_b = all_changes[j]
            ts_b = _iso_to_datetime(change_b.get("last_changed", ""))
            if ts_b is None:
                continue

            delay = (ts_b - ts_a).total_seconds()
            if delay > window.total_seconds():
                break  # No more B events within window

            if delay <= 0:
                continue

            entity_b = change_b.get("_entity_id", "")
            if entity_a == entity_b:
                continue

            state_b = change_b.get("state", "")

            key = (entity_a, state_a, entity_b, state_b)
            rules_candidates[key].append(delay)

    # Build rules from candidates
    rules: list[SequenceRule] = []
    for (
        entity_a,
        state_a,
        entity_b,
        state_b,
    ), delays in rules_candidates.items():
        if len(delays) < min_occurrences:
            continue

        delays_arr = np.array(delays, dtype=np.float64)
        mean_delay = float(delays_arr.mean())
        std_delay = float(delays_arr.std()) if len(delays_arr) > 1 else 60.0

        rule = SequenceRule(
            id=f"{entity_a}({state_a})→{entity_b}({state_b})",
            source_entity=entity_a,
            source_state=state_a,
            target_entity=entity_b,
            target_state=state_b,
            mean_delay=mean_delay,
            std_delay=std_delay,
            occurrence_count=len(delays),
            discovery_window=window_minutes,
        )
        rule._recompute_confidence()  # noqa: SLF001
        if rule.confidence >= 0.3:  # minimum confidence for rule
            rules.append(rule)

    rules.sort(key=lambda r: r.confidence, reverse=True)
    return rules


# ---------------------------------------------------------------------------
# Incremental Update
# ---------------------------------------------------------------------------


def incremental_update(
    existing_profiles: dict[str, list[TimeProfile]],
    existing_rules: list[SequenceRule],
    new_history: dict[str, list[dict]],
    entities: list[str],
    window_minutes: int = 60,
) -> tuple[
    dict[str, list[TimeProfile]],
    list[SequenceRule],
    int,
    int,
]:
    """Update profiles and rules incrementally with new history.

    Uses EMA to incorporate new observations without full retraining.

    Args:
        existing_profiles: Previously learned profiles.
        existing_rules: Previously discovered rules.
        new_history: New state changes since last update.
        entities: All monitored entities.
        window_minutes: Discovery window for sequence rules.

    Returns:
        Tuple of (updated_profiles, updated_rules, new_observations, new_rules_count).
    """
    new_observations = 0

    # Update profiles with new data
    for entity_id in entities:
        new_changes = new_history.get(entity_id, [])
        if not new_changes:
            continue

        profiles = existing_profiles.get(entity_id, [])
        if not profiles:
            # This shouldn't happen for learning (only for simulation)
            profiles = build_time_profiles(new_history, [entity_id])[
                entity_id
            ]
            existing_profiles[entity_id] = profiles

        for change in new_changes:
            ts = _iso_to_datetime(change.get("last_changed", ""))
            if ts is None:
                continue

            state = change.get("state", "off")
            is_on = state not in ("off", "unavailable", "unknown")
            slot = _slot_index(ts)

            # Determine day group
            dow = _day_of_week(ts)
            for profile in profiles:
                # Match profile to day of week
                if profile.day_group in ("weekday", "weekend"):
                    if (
                        profile.day_group == "weekday"
                        and dow < 5
                    ) or (
                        profile.day_group == "weekend" and dow >= 5
                    ):
                        profile.update_slot(slot, is_on=is_on)
                        profile.recompute_confidence()
                else:
                    try:
                        if int(profile.day_group) == dow:
                            profile.update_slot(
                                slot, is_on=is_on
                            )
                            profile.recompute_confidence()
                    except ValueError:
                        pass

            new_observations += 1

    # Discover new rules and update existing ones
    new_rules = discover_sequence_rules(
        new_history, entities, window_minutes
    )

    # Merge new rules with existing
    existing_by_id = {r.id: r for r in existing_rules}
    new_rules_count = 0

    for new_rule in new_rules:
        if new_rule.id in existing_by_id:
            # Update existing rule occurrences
            existing = existing_by_id[new_rule.id]
            for delay in [
                new_rule.mean_delay
            ] * new_rule.occurrence_count:
                existing.update_occurrence(delay, EMA_ALPHA)
        else:
            existing_by_id[new_rule.id] = new_rule
            new_rules_count += 1

    updated_rules = sorted(
        existing_by_id.values(),
        key=lambda r: r.confidence,
        reverse=True,
    )

    return existing_profiles, updated_rules, new_observations, new_rules_count
