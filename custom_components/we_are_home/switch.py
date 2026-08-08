"""Switch entity for We Are Home presence simulation.

Exposes a toggle-able switch that starts and stops the simulation.
Provides real-time attributes about simulation state and learning metrics.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from .const import DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the We Are Home switch from a config entry."""
    coordinator_data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = coordinator_data.get("coordinator")
    if coordinator is None:
        _LOGGER.error("No coordinator found for entry %s", entry.entry_id)
        return

    name = entry.data.get("name", DEFAULT_NAME)
    switch = PresenceSimulationSwitch(coordinator, entry.entry_id, name)
    async_add_entities([switch])


class PresenceSimulationSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle presence simulation on/off."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: Any,
        entry_id: str,
        name: str,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry_id}"
        self._attr_is_on = False
        self._simulation = coordinator.simulation

    @property
    def icon(self) -> str:
        """Return the icon for the switch."""
        return "mdi:home-account" if self._attr_is_on else "mdi:home-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose real-time simulation and learning metrics."""
        coordinator = self.coordinator
        simulation = coordinator.simulation if coordinator else None

        attrs: dict[str, Any] = {
            "entities_controlled": len(
                self.coordinator.config_entry.data.get("entities", [])
            ),
                "profiles_loaded": getattr(
                coordinator, "profiles_loaded", 0
            ),
                "profiles_ready": getattr(
                coordinator, "profiles_ready", 0
            ),
                "sequence_rules": getattr(
                coordinator, "sequence_rules_count", 0
            ),
                "last_training": getattr(
                coordinator, "last_training", None
            ),
                "active_boosts": 0,
                "simulation_uptime": None,
                "commands_sent": 0,
            }

        if simulation is not None:
            attrs["active_boosts"] = len(
                getattr(simulation, "active_boosts", [])
            )
            if getattr(simulation, "started_at", None) is not None:
                from datetime import UTC, datetime

                delta = datetime.now(UTC) - simulation.started_at
                attrs["simulation_uptime"] = round(
                    delta.total_seconds() / 3600, 2
                )
            attrs["commands_sent"] = getattr(
                simulation, "commands_sent", 0
            )

        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the presence simulation."""
        _LOGGER.info("Starting We Are Home simulation")
        simulation = self.coordinator.simulation if self.coordinator else None
        if simulation is not None:
            await simulation.start()
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the presence simulation."""
        _LOGGER.info("Stopping We Are Home simulation")
        simulation = self.coordinator.simulation if self.coordinator else None
        if simulation is not None:
            await simulation.stop()
            self._attr_is_on = False
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator is not None
