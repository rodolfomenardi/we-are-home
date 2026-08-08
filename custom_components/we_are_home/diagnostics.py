"""Diagnostics endpoint for We Are Home integration.

Exposes learned profiles summary, confidence levels, sequence rules,
and learning run history for debugging and support.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import history_reader, storage
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Fields to redact in diagnostics output
_REDACT = {"entity_id"}  # entity_ids are public anyway, nothing sensitive


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Called by Home Assistant's diagnostics feature.
    """
    coordinator_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = coordinator_data.get("coordinator")

    # Load stored data
    profiles = await storage.load_all_profiles(hass)
    rules = await storage.load_sequence_rules(hass)
    learning_log = await storage.load_learning_log(hass, max_entries=20)
    recorder_info = await history_reader.get_recorder_info(hass)

    # Per-entity breakdown
    entities_detail = {}
    for entity_id, profile_list in profiles.items():
        if isinstance(profile_list, dict):
            profile_list = profile_list.get("profiles", [])

        slots_with_data = 0
        total_observations = 0
        max_confidence = 0.0

        for profile in profile_list:
            plist = profile.get("profiles", [profile])
            for p in plist if isinstance(plist, list) else [plist]:
                total_observations += p.get("total_observations", 0)
                for slot in p.get("slots", []):
                    if slot.get("sample_count", 0) > 0:
                        slots_with_data += 1
                conf = p.get("confidence", 0)
                if conf > max_confidence:
                    max_confidence = conf

        # Maturity level
        avg_obs = total_observations / 96 if total_observations > 0 else 0
        if avg_obs < 3:
            maturity = "COLD"
        elif avg_obs < 14:
            maturity = "WARM"
        elif avg_obs < 30:
            maturity = "HOT"
        else:
            maturity = "STABLE"

        entities_detail[entity_id] = {
            "confidence": round(max_confidence, 3),
            "maturity": maturity,
            "total_observations": total_observations,
            "slots_with_data": slots_with_data,
            "last_updated": (
                profile_list[-1].get("last_updated")
                if profile_list
                else None
            ),
        }

    # Sequence rule summary
    rules_summary = {
        "total": len(rules),
        "by_source": {},
        "avg_confidence": round(
            sum(r.get("confidence", 0) for r in rules) / max(len(rules), 1),
            3,
        ),
        "most_frequent": sorted(
            rules,
            key=lambda r: r.get("occurrence_count", 0),
            reverse=True,
        )[:5],
    }

    for r in rules:
        src = r.get("source_entity", "unknown")
        rules_summary["by_source"][src] = (
            rules_summary["by_source"].get(src, 0) + 1
        )

    diagnostics_data = {
        "config": {
            "entities": entry.data.get("entities", []),
            "learning_interval": entry.data.get("learning_interval"),
            "simulation_interval": entry.data.get("simulation_interval"),
            "min_confidence": entry.data.get("min_confidence"),
            "sequence_window": entry.data.get("sequence_window"),
        },
        "profiles_summary": {
            "total_entities": len(profiles),
            "ready_entities": sum(
                1
                for e in entities_detail.values()
                if e["maturity"] in ("HOT", "STABLE")
            ),
            "entities": entities_detail,
        },
        "sequence_rules": rules_summary,
        "learning_log": learning_log[-10:],
        "recorder": recorder_info,
    }

    if coordinator is not None:
        diagnostics_data["coordinator"] = {
            "profiles_loaded": getattr(
                coordinator, "profiles_loaded", 0
            ),
            "profiles_ready": getattr(
                coordinator, "profiles_ready", 0
            ),
            "sequence_rules_count": getattr(
                coordinator, "sequence_rules_count", 0
            ),
            "last_training": str(
                getattr(coordinator, "last_training", None)
            ),
            "simulation_active": (
                coordinator.simulation is not None
                and coordinator.simulation.active
            ),
        }

    return diagnostics_data
