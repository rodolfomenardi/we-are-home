"""Data model classes for We Are Home integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EntityConfig:
    """Configuration for a single monitored entity."""

    entity_id: str
    domain: str
    enabled: bool = True
    min_confidence_threshold: float = 0.3
    restore_on_stop: bool = True
    profile: dict | None = None  # serialised TimeProfile

    @property
    def domain(self) -> str:  # type: ignore[override]
        """Extract domain from entity_id."""
        return self.entity_id.split(".", 1)[0]


@dataclass
class SimulationState:
    """Runtime state of an active simulation instance."""

    instance_id: str
    active: bool = False
    started_at: datetime | None = None
    entities: dict[str, str] = field(default_factory=dict)
    active_boosts: list[dict] = field(default_factory=list)
    override_params: dict[str, Any] = field(default_factory=dict)
