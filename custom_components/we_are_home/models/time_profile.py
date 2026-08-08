"""Time profile model for We Are Home integration.

TimeProfile captures the probabilistic behaviour of a single entity
across 96 fifteen-minute windows (24h) for a specific day group
(e.g. weekday or weekend).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..const import EMA_ALPHA, SLOTS_PER_DAY


@dataclass
class TimeSlot:
    """A single 15-minute time window within a day profile."""

    slot_index: int  # 0–95 (0 = 00:00-00:15, 95 = 23:45-00:00)
    p_on: float = 0.0
    p_transition: float = 0.0
    mean_duration_on: float = 0.0  # minutes
    std_duration_on: float = 0.0  # minutes
    sample_count: int = 0
    transition_count: int = 0
    duration_count: int = 0
    last_updated: datetime | None = None


@dataclass
class TimeProfile:
    """Probabilistic profile for a single entity × day group.

    Captures P(on), P(transition), and duration distributions for
    each 15-minute window across a 24-hour day. Updated incrementally
    via exponential moving average (EMA).
    """

    entity_id: str
    day_group: str = "weekday"  # "weekday" or "weekend"
    slots: list[TimeSlot] = field(default_factory=list)
    confidence: float = 0.0
    total_observations: int = 0
    last_updated: datetime | None = None

    def __post_init__(self) -> None:
        """Initialise slots array if empty."""
        if not self.slots:
            self.slots = [
                TimeSlot(slot_index=i) for i in range(SLOTS_PER_DAY)
            ]

    def update_slot(
        self,
        slot_index: int,
        is_on: bool,
        duration_on: float = 0.0,
        alpha: float = EMA_ALPHA,
    ) -> None:
        """Update a single slot with EMA.

        Args:
            slot_index: Which 15-min slot (0-95).
            is_on: Whether entity was ON during this slot.
            duration_on: Duration the entity was ON (minutes).
            alpha: EMA weight for new observation (0-1).
        """
        if not 0 <= slot_index < SLOTS_PER_DAY:
            return

        slot = self.slots[slot_index]

        # EMA update for p_on
        new_p_on = 1.0 if is_on else 0.0
        if slot.sample_count == 0:
            slot.p_on = new_p_on
        else:
            slot.p_on = (1 - alpha) * slot.p_on + alpha * new_p_on

        # EMA update for duration (recorded on both on and off observations
        # so the duration of an ON period is attributed to its ending slot).
        # Zero-duration observations (the ON entry, where the duration is
        # not yet known) never pollute the duration statistics.
        if duration_on > 0:
            if slot.duration_count == 0:
                slot.mean_duration_on = duration_on
                slot.std_duration_on = 0.0
            else:
                # Welford-style update for mean and std
                old_mean = slot.mean_duration_on
                slot.mean_duration_on = (
                    (1 - alpha) * old_mean + alpha * duration_on
                )
                slot.std_duration_on = (
                    (1 - alpha) * slot.std_duration_on
                    + alpha * abs(duration_on - old_mean)
                )
            slot.duration_count += 1

        slot.sample_count += 1
        slot.last_updated = datetime.now()

    def update_p_transition(
        self,
        slot_index: int,
        transitioned: bool,
        alpha: float = EMA_ALPHA,
    ) -> None:
        """Update transition probability for a slot."""
        if not 0 <= slot_index < SLOTS_PER_DAY:
            return

        slot = self.slots[slot_index]
        new_val = 1.0 if transitioned else 0.0
        if slot.transition_count == 0:
            slot.p_transition = new_val
        else:
            slot.p_transition = (
                (1 - alpha) * slot.p_transition + alpha * new_val
            )
        slot.transition_count += 1

    def recompute_confidence(self) -> float:
        """Recompute overall confidence from slot sample counts.

        Returns a value between 0.0 (no data) and 1.0 (fully learned).
        """
        total_samples = sum(s.sample_count for s in self.slots)
        self.total_observations = total_samples

        if total_samples == 0:
            self.confidence = 0.0
            return 0.0

        # Confidence grows with sample count and slot coverage
        slots_with_data = sum(1 for s in self.slots if s.sample_count > 0)
        coverage = slots_with_data / SLOTS_PER_DAY

        # Logarithmic confidence: 3 samples = 0.3, 14 = 0.6, 30 = 0.85
        import math

        avg_samples = total_samples / SLOTS_PER_DAY
        sample_confidence = min(1.0, math.log2(max(avg_samples, 1)) / 6.0)

        # Combined: 70% sample weight, 30% coverage weight
        self.confidence = 0.7 * sample_confidence + 0.3 * coverage
        return self.confidence

    def maturity_level(self) -> str:
        """Return the maturity level based on average observations."""
        from ..const import (
            MATURITY_COLD,
            MATURITY_HOT,
            MATURITY_STABLE,
            MATURITY_WARM,
        )

        if not self.slots:
            return MATURITY_COLD

        avg = self.total_observations / SLOTS_PER_DAY
        if avg < 3:
            return MATURITY_COLD
        if avg < 14:
            return MATURITY_WARM
        if avg < 30:
            return MATURITY_HOT
        return MATURITY_STABLE

    def to_dict(self) -> dict:
        """Serialise to dict for JSON storage."""
        return {
            "entity_id": self.entity_id,
            "day_group": self.day_group,
            "confidence": self.confidence,
            "total_observations": self.total_observations,
            "last_updated": (
                self.last_updated.isoformat()
                if self.last_updated
                else None
            ),
            "slots": [
                {
                    "slot_index": s.slot_index,
                    "p_on": s.p_on,
                    "p_transition": s.p_transition,
                    "mean_duration_on": s.mean_duration_on,
                    "std_duration_on": s.std_duration_on,
                    "sample_count": s.sample_count,
                    "transition_count": s.transition_count,
                    "duration_count": s.duration_count,
                    "last_updated": (
                        s.last_updated.isoformat()
                        if s.last_updated
                        else None
                    ),
                }
                for s in self.slots
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> TimeProfile:
        """Deserialise from dict."""
        profile = cls(
            entity_id=data["entity_id"],
            day_group=data.get("day_group", "weekday"),
            confidence=data.get("confidence", 0.0),
            total_observations=data.get("total_observations", 0),
            last_updated=(
                datetime.fromisoformat(data["last_updated"])
                if data.get("last_updated")
                else None
            ),
        )
        profile.slots = [
            TimeSlot(
                slot_index=s["slot_index"],
                p_on=s.get("p_on", 0.0),
                p_transition=s.get("p_transition", 0.0),
                mean_duration_on=s.get("mean_duration_on", 0.0),
                std_duration_on=s.get("std_duration_on", 0.0),
                sample_count=s.get("sample_count", 0),
                transition_count=s.get("transition_count", 0),
                duration_count=s.get("duration_count", 0),
                last_updated=(
                    datetime.fromisoformat(s["last_updated"])
                    if s.get("last_updated")
                    else None
                ),
            )
            for s in data.get("slots", [])
        ]
        return profile
