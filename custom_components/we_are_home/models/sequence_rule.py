"""Sequence rule model for We Are Home integration.

SequenceRule captures temporal associations between entity pairs (A→B)
discovered from historical data. ActiveBoost manages a temporary
probability multiplier during simulation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class SequenceRule:
    """A temporal association rule between two entities.

    Learns that when source_entity changes to source_state,
    target_entity tends to change to target_state after mean_delay
    (± std_delay) seconds.
    """

    id: str
    source_entity: str
    source_state: str
    target_entity: str
    target_state: str
    mean_delay: float = 0.0  # seconds
    std_delay: float = 0.0  # seconds
    occurrence_count: int = 1
    confidence: float = 0.0
    boost_factor: float = 2.0
    discovery_window: int = 60  # minutes
    last_observed: datetime | None = None

    def update_occurrence(
        self,
        delay_seconds: float,
        alpha: float = 0.3,
    ) -> None:
        """Update delay statistics with a new occurrence using EMA.

        Args:
            delay_seconds: Observed delay between source and target.
            alpha: EMA weight for new observation.
        """
        if self.occurrence_count == 0:
            self.mean_delay = delay_seconds
            self.std_delay = 0.0
        else:
            old_mean = self.mean_delay
            self.mean_delay = (
                (1 - alpha) * old_mean + alpha * delay_seconds
            )
            self.std_delay = (
                (1 - alpha) * self.std_delay
                + alpha * abs(delay_seconds - old_mean)
            )

        self.occurrence_count += 1
        self.last_observed = datetime.now(UTC)
        self._recompute_confidence()

    def _recompute_confidence(self) -> None:
        """Recompute statistical confidence.

        Confidence grows with occurrence count (logarithmic) and
        shrinks with delay variability (lower std = higher confidence).
        """
        if self.occurrence_count < 3:
            self.confidence = 0.0
            return

        # Count confidence: logarithmic from 3–30 occurrences
        count_score = min(
            1.0, math.log2(self.occurrence_count / 3.0) / 4.0
        )

        # Delay stability: lower CV = higher confidence
        cv = (
            abs(self.std_delay / self.mean_delay)
            if self.mean_delay > 0
            else 1.0
        )
        stability_score = max(0.0, 1.0 - cv)

        self.confidence = 0.6 * count_score + 0.4 * stability_score

    def to_dict(self) -> dict:
        """Serialise to dict for JSON storage."""
        return {
            "id": self.id,
            "source_entity": self.source_entity,
            "source_state": self.source_state,
            "target_entity": self.target_entity,
            "target_state": self.target_state,
            "mean_delay": self.mean_delay,
            "std_delay": self.std_delay,
            "occurrence_count": self.occurrence_count,
            "confidence": self.confidence,
            "boost_factor": self.boost_factor,
            "discovery_window": self.discovery_window,
            "last_observed": (
                self.last_observed.isoformat()
                if self.last_observed
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SequenceRule:
        """Deserialise from dict."""
        return cls(
            id=data["id"],
            source_entity=data["source_entity"],
            source_state=data["source_state"],
            target_entity=data["target_entity"],
            target_state=data["target_state"],
            mean_delay=data.get("mean_delay", 0.0),
            std_delay=data.get("std_delay", 0.0),
            occurrence_count=data.get("occurrence_count", 1),
            confidence=data.get("confidence", 0.0),
            boost_factor=data.get("boost_factor", 2.0),
            discovery_window=data.get("discovery_window", 60),
            last_observed=(
                datetime.fromisoformat(data["last_observed"])
                if data.get("last_observed")
                else None
            ),
        )


@dataclass
class ActiveBoost:
    """A temporary probability boost from a triggered sequence rule.

    When entity A changes state, this boost increases entity B's
    probability of changing state, decaying over time via Gaussian.
    """

    rule_id: str
    target_entity: str
    multiplier: float = 2.0
    peak_multiplier: float = 2.0
    activated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    mean_delay: float = 0.0
    std_delay: float = 60.0

    @property
    def expires_at(self) -> datetime:
        """Boost decays to 1.0 at mean_delay + 3*std_delay."""
        duration = timedelta(
            seconds=self.mean_delay + 3 * self.std_delay
        )
        return self.activated_at + duration

    def current_multiplier(self, at_time: datetime | None = None) -> float:
        """Compute current boost multiplier using Gaussian decay.

        Args:
            at_time: Reference time (default: now UTC).

        Returns:
            Multiplier ≥ 1.0. Returns 1.0 if boost has expired.
        """
        if at_time is None:
            at_time = datetime.now(UTC)
        if at_time.tzinfo is None:
            at_time = at_time.replace(tzinfo=UTC)

        if at_time >= self.expires_at:
            return 1.0

        elapsed = (at_time - self.activated_at).total_seconds()
        if elapsed <= 0:
            return self.peak_multiplier

        # Gaussian decay centered at mean_delay
        sigma = max(self.std_delay, 1.0)
        gaussian = math.exp(
            -0.5 * ((elapsed - self.mean_delay) / sigma) ** 2
        )
        # Scale from [0, 1] to [1.0, peak_multiplier]
        self.multiplier = 1.0 + (self.peak_multiplier - 1.0) * gaussian
        return self.multiplier

    def is_expired(self, at_time: datetime | None = None) -> bool:
        """Check if the boost has passed its full decay window.

        A boost is only considered expired once it has been active for
        mean_delay + 3*std_delay seconds. Checking the multiplier instead
        would expire freshly-triggered boosts: right after activation the
        Gaussian is still near zero (the peak sits at mean_delay), so the
        multiplier is ~1.0 even though the boost is about to rise.
        """
        if at_time is None:
            at_time = datetime.now(UTC)
        if at_time.tzinfo is None:
            at_time = at_time.replace(tzinfo=UTC)
        return at_time >= self.expires_at
