"""We Are Home — Intelligent Presence Simulation for Home Assistant.

Learns device usage patterns from recorder history and generates
realistic synthetic presence simulations using probabilistic models
(TimeProfiles with EMA, pairwise SequenceRules with boost system).

Distributed via HACS. 100% local — no cloud dependencies.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the We Are Home integration (legacy YAML, not used)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up We Are Home from a config entry.

    Creates a DataUpdateCoordinator for periodic learning updates
    and registers the switch platform for simulation control.
    """
    hass.data.setdefault(DOMAIN, {})

    from .coordinator import WeAreHomeCoordinator

    coordinator = WeAreHomeCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    from . import services as svc

    await svc.async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info(
        "We Are Home: %d entities configured for learning and simulation",
        len(entry.data.get("entities", [])),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )

    if unload_ok:
        coordinator_data = hass.data[DOMAIN].pop(entry.entry_id, {})
        coordinator = coordinator_data.get("coordinator")
        if coordinator is not None:
            await coordinator.async_shutdown()

    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle config entry updates (OptionsFlow changes)."""
    await hass.config_entries.async_reload(entry.entry_id)
