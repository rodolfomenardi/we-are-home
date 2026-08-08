"""Simulation engine for We Are Home integration.

Generates synthetic device commands based on learned TimeProfiles
and SequenceRules. Uses Gaussian noise for realistic variation and
boost-triggered probability adjustments for cross-entity sequencing.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceNotFound

from .const import (
    DEFAULT_BOOST_FACTOR,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_SIMULATION_INTERVAL,
    EVENT_COMMAND,
    EVENT_SEQUENCE_TRIGGERED,
    SECONDS_PER_SLOT,
    SLOTS_PER_DAY,
)
from .models.sequence_rule import ActiveBoost, SequenceRule

_LOGGER = logging.getLogger(__name__)


class SimulationEngine:
    """Generates realistic presence simulation from learned profiles."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        coordinator: Any,
    ) -> None:
        """Initialise the simulation engine."""
        self.hass = hass
        self.config_entry = config_entry
        self.coordinator = coordinator

        self.active = False
        self.started_at: datetime | None = None
        self._pre_simulation_states: dict[str, str] = {}
        self._boost_manager = BoostManager()
        self._commands_sent: int = 0
        self._grace_period: dict[str, datetime] = {}
        self._running = False

    @property
    def commands_sent(self) -> int:
        """Return total commands sent during this simulation."""
        return self._commands_sent

    @property
    def active_boosts(self) -> list[ActiveBoost]:
        """Return currently active sequence boosts."""
        return self._boost_manager.active_boosts

    async def start(self) -> None:
        """Start the simulation.

        Captures current states for optional restoration, starts the
        simulation tick loop.
        """
        entities = self.config_entry.data.get("entities", [])
        if not entities:
            _LOGGER.warning("No entities configured; simulation not started")
            return

        self._pre_simulation_states = await _capture_entity_states(
            self.hass, entities
        )
        self._boost_manager.clear()

        self.active = True
        self.started_at = datetime.now(UTC)
        self._commands_sent = 0
        self._running = True

        _LOGGER.info(
            "Simulation started with %d entities; pre-states captured",
            len(entities),
        )

    async def stop(self) -> None:
        """Stop the simulation.

        Optionally restores pre-simulation states if configured.
        """
        self._running = False
        self.active = False
        self._boost_manager.clear()

        restore = self.config_entry.data.get("restore_states", True)
        if restore and self._pre_simulation_states:
            await _restore_entity_states(
                self.hass, self._pre_simulation_states
            )
            _LOGGER.info(
                "Simulation stopped; %d entities restored to pre-simulation states",
                len(self._pre_simulation_states),
            )
        else:
            _LOGGER.info("Simulation stopped (no state restoration)")

        self._pre_simulation_states.clear()

    async def tick(self) -> int:
        """Execute one simulation tick.

        Evaluates current time-slot probabilities, applies sequence
        boosts, and sends commands. Called at simulation_interval.

        Returns:
            Number of commands sent this tick.
        """
        if not self.active:
            return 0

        entities = self.config_entry.data.get("entities", [])
        min_confidence = self.config_entry.data.get(
            "min_confidence", DEFAULT_MIN_CONFIDENCE
        )
        boost_factor = self.config_entry.data.get(
            "boost_factor", DEFAULT_BOOST_FACTOR
        )

        now = datetime.now()
        slot = _time_slot_index(now)
        day = now.weekday()  # 0=Mon, 6=Sun
        day_group = "weekday" if day < 5 else "weekend"

        commands_sent = 0

        # Load profiles
        profiles = getattr(self.coordinator, "_profiles", {})

        for entity_id in entities:
            entity_profiles = profiles.get(entity_id, [])
            if not entity_profiles:
                continue

            # Find matching day-group profile
            profile = None
            if isinstance(entity_profiles, list):
                for p in entity_profiles:
                    if isinstance(p, dict):
                        if p.get("day_group") == day_group:
                            profile = p
                            break

            if profile is None:
                continue

            # Check confidence threshold
            confidence = profile.get("confidence", 0)
            if confidence < min_confidence:
                continue

            # Get current state
            current_state = self.hass.states.get(entity_id)
            is_currently_on = (
                current_state.state not in ("off", "unavailable", "unknown")
                if current_state
                else False
            )

            # Find slot probability
            slots = profile.get("slots", [])
            slot_data = slots[slot] if slot < len(slots) else {}
            p_on = slot_data.get("p_on", 0.0)

            # Apply active sequence boosts
            boost_mult = self._boost_manager.get_boost(entity_id, now)
            p_on *= boost_mult

            # Skip if entity was manually operated recently
            if self._in_grace_period(entity_id, now):
                continue

            # Decide whether to change state
            p_clamped = max(0.0, min(1.0, p_on))
            rand_val = random.random()

            target_on = rand_val < p_clamped

            if target_on and not is_currently_on:
                await self._send_command(entity_id, SERVICE_TURN_ON)
                self._boost_manager.trigger(
                    entity_id,
                    "on",
                    profiles,
                    boost_factor,
                    self.coordinator,
                )
                commands_sent += 1

            elif not target_on and is_currently_on:
                await self._send_command(entity_id, SERVICE_TURN_OFF)
                commands_sent += 1

        self._commands_sent += commands_sent
        return commands_sent

    async def _send_command(
        self, entity_id: str, service: str
    ) -> None:
        """Send a Home Assistant service call and fire event.

        Handles entity conflict detection: skips entities that were
        manually operated within the grace period.
        """
        domain = entity_id.split(".", 1)[0]

        try:
            await self.hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id},
                blocking=False,
            )
        except (ServiceNotFound, Exception) as exc:
            _LOGGER.debug(
                "Failed to %s %s: %s", service, entity_id, exc
            )

        # Mark grace period for conflict detection
        self._grace_period[entity_id] = datetime.now()

        # Fire event for automations
        self.hass.bus.async_fire(
            EVENT_COMMAND,
            {
                "entity_id": entity_id,
                "service": f"{domain}.{service}",
                "reason": "simulation_tick",
            },
        )

    def _in_grace_period(
        self, entity_id: str, now: datetime
    ) -> bool:
        """Check if entity was recently manually operated.

        Implements last-command-wins conflict resolution.
        """
        if entity_id not in self._grace_period:
            return False

        interval = self.config_entry.data.get(
            "simulation_interval", DEFAULT_SIMULATION_INTERVAL
        )
        elapsed = (now - self._grace_period[entity_id]).total_seconds()
        return elapsed < interval


class BoostManager:
    """Manages active sequence boosts for the simulation engine."""

    def __init__(self) -> None:
        """Initialise boost manager."""
        self._boosts: list[ActiveBoost] = []

    @property
    def active_boosts(self) -> list[ActiveBoost]:
        """Return currently active boosts (non-expired)."""
        now = datetime.now(UTC)
        return [b for b in self._boosts if not b.is_expired(now)]

    def trigger(
        self,
        entity_id: str,
        new_state: str,
        profiles: dict[str, Any],
        boost_factor: float,
        coordinator: Any,
    ) -> None:
        """Trigger sequence rules when an entity changes state.

        Looks up matching rules and creates ActiveBoost instances.

        Args:
            entity_id: Entity that just changed state.
            new_state: The new state (e.g., "on").
            profiles: All learned profiles.
            boost_factor: Default boost multiplier.
            coordinator: The WeAreHomeCoordinator for rule access.
        """
        rules_data = getattr(coordinator, "_sequence_rules", [])
        if not rules_data:
            return

        for rule_dict in rules_data:
            rule = SequenceRule.from_dict(rule_dict)
            if (
                rule.source_entity == entity_id
                and rule.source_state == new_state
                and rule.confidence >= 0.3
            ):
                boost = ActiveBoost(
                    rule_id=rule.id,
                    target_entity=rule.target_entity,
                    peak_multiplier=boost_factor,
                    mean_delay=rule.mean_delay,
                    std_delay=rule.std_delay,
                )
                self._boosts.append(boost)

                # Fire sequence event
                if hasattr(coordinator, "hass"):
                    coordinator.hass.bus.async_fire(
                        EVENT_SEQUENCE_TRIGGERED,
                        {
                            "rule_id": rule.id,
                            "source": entity_id,
                            "target": rule.target_entity,
                            "mean_delay": rule.mean_delay,
                            "boost_multiplier": boost_factor,
                        },
                    )

        # Clean expired
        self._boosts = self.active_boosts

    def get_boost(
        self, entity_id: str, at_time: datetime | None = None
    ) -> float:
        """Get combined boost multiplier for an entity.

        When multiple rules target the same entity (conflicting
        rules A→C and B→C), boosts are shared proportionally using
        their product (capped at peak_multiplier × 2 to prevent
        runaway amplification).

        Returns:
            Multiplier ≥ 1.0.
        """
        if at_time is None:
            at_time = datetime.now(UTC)

        multipliers = []
        for boost in self._boosts:
            if boost.target_entity == entity_id:
                mult = boost.current_multiplier(at_time)
                if mult > 1.0:
                    multipliers.append(mult)

        if not multipliers:
            return 1.0

        # Combine: product of boosts, capped
        combined = 1.0
        for m in multipliers:
            combined *= m

        return min(combined, 5.0)  # Cap at 5× to prevent runaway

    def clear(self) -> None:
        """Remove all active boosts."""
        self._boosts.clear()


# ---------------------------------------------------------------------------
# State Capture / Restore
# ---------------------------------------------------------------------------


async def _capture_entity_states(
    hass: HomeAssistant, entities: list[str]
) -> dict[str, str]:
    """Capture current states of all entities.

    Returns:
        Dict entity_id → state string.
    """
    states: dict[str, str] = {}
    for entity_id in entities:
        state_obj = hass.states.get(entity_id)
        if state_obj is not None:
            states[entity_id] = state_obj.state
        else:
            states[entity_id] = "off"
    return states


async def _restore_entity_states(
    hass: HomeAssistant, captured: dict[str, str]
) -> None:
    """Restore entities to their pre-simulation states."""
    for entity_id, target_state in captured.items():
        domain = entity_id.split(".", 1)[0]
        is_on = target_state not in ("off", "unavailable", "unknown")
        service = SERVICE_TURN_ON if is_on else SERVICE_TURN_OFF

        try:
            await hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id},
                blocking=False,
            )
        except (ServiceNotFound, Exception) as exc:
            _LOGGER.debug(
                "Failed to restore %s to %s: %s",
                entity_id,
                target_state,
                exc,
            )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _time_slot_index(dt: datetime) -> int:
    """Map a datetime to a 15-min slot index (0-95)."""
    minutes = dt.hour * 60 + dt.minute
    return min(minutes // 15, SLOTS_PER_DAY - 1)
