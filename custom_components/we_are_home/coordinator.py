"""DataUpdateCoordinator for We Are Home integration.

Orchestrates periodic learning updates and simulation tick loops,
maintaining learned profiles and sequence rules in memory and storage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DEFAULT_LEARNING_INTERVAL,
    DEFAULT_MIN_CONFIDENCE,
    DOMAIN,
)
from . import history_reader, storage
from .models.learner import (
    auto_detect_day_groups,
    build_time_profiles,
    discover_sequence_rules,
    incremental_update,
)
from .models.sequence_rule import SequenceRule

_LOGGER = logging.getLogger(__name__)


class WeAreHomeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator managing learning and simulation for We Are Home."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Initialise coordinator."""
        learning_interval = entry.data.get(
            "learning_interval", DEFAULT_LEARNING_INTERVAL
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=learning_interval),
        )

        self.config_entry = entry
        self._profiles: dict[str, list[dict]] = {}
        self._sequence_rules: list[dict] = []
        self._last_learning: datetime | None = None

        self.profiles_loaded: int = 0
        self.profiles_ready: int = 0
        self.sequence_rules_count: int = 0
        self.last_training: datetime | None = None

        # Lazy simulation engine
        self.simulation: SimulationEngine | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Periodic learning update.

        Called by DataUpdateCoordinator at the configured interval.
        Queries recorder for new state changes and incrementally
        updates profiles and sequence rules.
        """
        entities = self.config_entry.data.get("entities", [])
        if not entities:
            return {"profiles_loaded": 0, "profiles_ready": 0}

        cycle_start = datetime.now()
        is_first_run = not self._profiles

        try:
            # Get recent history since last update
            since = (
                self._last_learning
                or datetime(2000, 1, 1)
            )
            _LOGGER.info(
                "Learning cycle start | first_run=%s since=%s entities=%d",
                is_first_run,
                since.isoformat() if since.year > 2000 else "epoch",
                len(entities),
            )
            new_history = await history_reader.get_recent_state_changes(
                self.hass, entities, since
            )
            history_events = sum(
                len(changes) for changes in new_history.values()
            )
            _LOGGER.debug(
                "History fetched | events=%d entities_with_changes=%d",
                history_events,
                len([e for e, ch in new_history.items() if ch]),
            )

            # Initial learning or incremental update
            if not self._profiles:
                # First run: load from storage or build from scratch
                stored_profiles = await storage.load_all_profiles(
                    self.hass
                )
                stored_rules = await storage.load_sequence_rules(
                    self.hass
                )

                if stored_profiles:
                    # Unwrap the {"entity_id": ..., "profiles": [...]} wrapper
                    # that storage uses, so downstream code iterates profile
                    # dicts (never dict keys).
                    self._profiles = {
                        eid: (
                            data.get("profiles", [data])
                            if isinstance(data, dict)
                            else data
                        )
                        for eid, data in stored_profiles.items()
                    }
                    self._sequence_rules = stored_rules
                    _LOGGER.info(
                        "Loaded %d profiles and %d rules from storage",
                        len(stored_profiles),
                        len(stored_rules),
                    )
                else:
                    # Build fresh from history
                    full_history = (
                        await history_reader.get_multi_entity_history(
                            self.hass, entities
                        )
                    )

                    raw_profiles = build_time_profiles(
                        full_history, entities
                    )
                    raw_profiles = auto_detect_day_groups(raw_profiles)

                    self._profiles = {
                        eid: [p.to_dict() for p in profiles]
                        for eid, profiles in raw_profiles.items()
                    }

                    for eid, profiles in self._profiles.items():
                        await storage.save_profile(self.hass, {
                            "entity_id": eid,
                            "profiles": profiles,
                        })

                    window = self.config_entry.data.get(
                        "sequence_window", 60
                    )
                    raw_rules = discover_sequence_rules(
                        full_history, entities, window
                    )
                    self._sequence_rules = [
                        r.to_dict() for r in raw_rules
                    ]

                    await storage.save_sequence_rules(
                        self.hass, self._sequence_rules
                    )

                    _LOGGER.info(
                        "Built %d profiles and discovered %d sequence rules",
                        len(self._profiles),
                        len(self._sequence_rules),
                    )
            else:
                # Incremental update
                from .models.learner import incremental_update as inc_upd

                profiles_raw = {}
                for eid, p_list in self._profiles.items():
                    from .models.time_profile import TimeProfile
                    profiles_raw[eid] = [
                        TimeProfile.from_dict(p) for p in p_list
                    ]

                rules_raw = [
                    SequenceRule.from_dict(r) for r in self._sequence_rules
                ]

                window = self.config_entry.data.get(
                    "sequence_window", 60
                )
                _, updated_rules, obs, new_rules = inc_upd(
                    profiles_raw,
                    rules_raw,
                    new_history,
                    entities,
                    window,
                )

                self._profiles = {
                    eid: [p.to_dict() for p in profs]
                    for eid, profs in profiles_raw.items()
                }
                self._sequence_rules = [
                    r.to_dict() for r in updated_rules
                ]

                # Persist
                for eid, profs in self._profiles.items():
                    await storage.save_profile(
                        self.hass,
                        {"entity_id": eid, "profiles": profs},
                    )
                await storage.save_sequence_rules(
                    self.hass, self._sequence_rules
                )

                # Log learning run
                await storage.append_learning_run(self.hass, {
                    "timestamp": datetime.now().isoformat(),
                    "entities_processed": len(entities),
                    "new_observations": obs,
                    "rules_discovered": new_rules,
                    "rules_updated": len(updated_rules) - new_rules,
                    "duration_ms": 0,
                    "errors": [],
                })

            # Update metrics
            self._last_learning = datetime.now()
            self.last_training = self._last_learning
            self.profiles_loaded = len(self._profiles)
            self.profiles_ready = sum(
                1
                for p in self._profiles.values()
                if any(
                    s.get("confidence", 0)
                    >= self.config_entry.data.get(
                        "min_confidence", DEFAULT_MIN_CONFIDENCE
                    )
                    for s in p
                )
            )
            self.sequence_rules_count = len(self._sequence_rules)

            duration = (datetime.now() - cycle_start).total_seconds()
            _LOGGER.info(
                "Learning cycle complete | profiles_loaded=%d profiles_ready=%d "
                "rules=%d duration=%.1fs",
                self.profiles_loaded,
                self.profiles_ready,
                self.sequence_rules_count,
                duration,
            )

            return {
                "profiles_loaded": self.profiles_loaded,
                "profiles_ready": self.profiles_ready,
                "sequence_rules": self.sequence_rules_count,
                "last_learning": self._last_learning,
            }

        except Exception as exc:
            _LOGGER.exception("Learning update failed")
            raise UpdateFailed(f"Learning update failed: {exc}") from exc

    async def async_shutdown(self) -> None:
        """Shutdown coordinator and simulation."""
        if self.simulation is not None and self.simulation.active:
            await self.simulation.stop()

    # Import simulation engine lazily to avoid circular imports
    def _get_simulation(self) -> Any:
        """Get or create the simulation engine."""
        if self.simulation is None:
            from .simulator import SimulationEngine

            self.simulation = SimulationEngine(
                self.hass, self.config_entry, self
            )
        return self.simulation
