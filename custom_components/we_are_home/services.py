"""Service handlers for We Are Home integration.

Exposes start, stop, train, get_profile, and list_rules services
that users can call from automations and scripts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from . import storage
from .const import (
    DOMAIN,
    SERVICE_GET_PROFILE,
    SERVICE_LIST_RULES,
    SERVICE_START,
    SERVICE_STOP,
    SERVICE_TRAIN,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service schemas
# ---------------------------------------------------------------------------

START_SCHEMA = vol.Schema(
    {
        vol.Optional("switch_id"): cv.string,
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Optional("restore_states"): cv.boolean,
    }
)

STOP_SCHEMA = vol.Schema(
    {
        vol.Optional("switch_id"): cv.string,
    }
)

TRAIN_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Optional("full_reset"): cv.boolean,
        vol.Optional("days_back"): vol.All(
            cv.positive_int, vol.Range(min=1, max=365)
        ),
    }
)

GET_PROFILE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.string,
    }
)

LIST_RULES_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.string,
        vol.Optional("min_confidence"): vol.All(
            cv.small_float, vol.Range(min=0.0, max=1.0)
        ),
    }
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all We Are Home services."""
    # Wrap handlers so hass is captured by closure.
    # HA calls service handlers as handler(call) with a single ServiceCall
    # argument, not handler(hass, call).

    def _bind(func):
        async def _wrapper(call: ServiceCall):
            return await func(hass, call)
        return _wrapper

    hass.services.async_register(
        DOMAIN,
        SERVICE_START,
        _bind(_handle_start),
        schema=START_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP,
        _bind(_handle_stop),
        schema=STOP_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TRAIN,
        _bind(_handle_train),
        schema=TRAIN_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PROFILE,
        _bind(_handle_get_profile),
        schema=GET_PROFILE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_RULES,
        _bind(_handle_list_rules),
        schema=LIST_RULES_SCHEMA,
    )
    _LOGGER.info("We Are Home services registered")


# ---------------------------------------------------------------------------
# Start / Stop / Train
# ---------------------------------------------------------------------------


async def _handle_start(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    """Handle we_are_home.start service call.

    Supports multi-instance via switch_id parameter.
    """
    switch_id = call.data.get("switch_id")
    _LOGGER.info("Service call: start | switch_id=%s", switch_id)
    coordinator = _resolve_coordinator(hass, switch_id)

    if coordinator is None:
        _LOGGER.warning("Service start: no coordinator found")
        return {"success": False, "error": "No configured instance found"}

    simulation = coordinator._get_simulation()  # noqa: SLF001

    # Apply overrides if provided
    entity_override = call.data.get("entity_id")
    restore_override = call.data.get("restore_states")
    if entity_override is not None:
        simulation._entity_override = entity_override  # noqa: SLF001
        _LOGGER.info("Service start: entity override=%s", entity_override)
    if restore_override is not None:
        simulation._restore_override = restore_override  # noqa: SLF001

    await simulation.start()
    _LOGGER.info("Service start: simulation started")

    return {
        "success": True,
        "instance_id": f"switch.{DOMAIN}_{coordinator.config_entry.entry_id[:8]}",
    }


async def _handle_stop(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    """Handle we_are_home.stop service call."""
    switch_id = call.data.get("switch_id")
    _LOGGER.info("Service call: stop | switch_id=%s", switch_id)
    coordinator = _resolve_coordinator(hass, switch_id)

    if coordinator is None:
        _LOGGER.warning("Service stop: no coordinator found")
        return {"success": False, "error": "No configured instance found"}

    simulation = coordinator._get_simulation()  # noqa: SLF001
    restored_count = len(simulation._pre_simulation_states)  # noqa: SLF001
    await simulation.stop()
    _LOGGER.info("Service stop: simulation stopped | restored=%d", restored_count)

    return {"success": True, "restored_entities": restored_count}


async def _handle_train(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    """Handle we_are_home.train service call.

    Supports full_reset (discard existing) and days_back (historical range).
    """
    switch_id = call.data.get("switch_id")
    coordinator = _resolve_coordinator(hass, switch_id)

    if coordinator is None:
        return {"success": False, "error": "No configured instance found"}

    full_reset = call.data.get("full_reset", False)
    days_back = call.data.get("days_back")
    target_entities = call.data.get("entity_id") or coordinator.config_entry.data.get(
        "entities", []
    )

    _LOGGER.info(
        "Service call: train | entities=%d full_reset=%s days_back=%s",
        len(target_entities),
        full_reset,
        days_back,
    )

    if full_reset:
        coordinator._profiles = {}  # noqa: SLF001
        coordinator._sequence_rules = []  # noqa: SLF001

    # Run learning cycle
    from . import history_reader
    from .models.learner import (
        auto_detect_day_groups,
        build_time_profiles,
        incremental_update,
    )

    history = await history_reader.get_multi_entity_history(
        hass, list(target_entities), days_back
    )

    if full_reset or not coordinator._profiles:  # noqa: SLF001
        raw = build_time_profiles(history, list(target_entities))
        raw = auto_detect_day_groups(raw)
        coordinator._profiles = {  # noqa: SLF001
            eid: [p.to_dict() for p in profs] for eid, profs in raw.items()
        }
    else:
        from .models.time_profile import TimeProfile
        from .models.sequence_rule import SequenceRule

        profiles_raw = {
            eid: [TimeProfile.from_dict(p) for p in plist]
            for eid, plist in coordinator._profiles.items()  # noqa: SLF001
        }
        rules_raw = [
            SequenceRule.from_dict(r)
            for r in coordinator._sequence_rules  # noqa: SLF001
        ]
        window = coordinator.config_entry.data.get("sequence_window", 60)
        _, updated, obs, new = incremental_update(
            profiles_raw, rules_raw, history,
            list(target_entities), window,
        )
        coordinator._profiles = {  # noqa: SLF001
            eid: [p.to_dict() for p in profs]
            for eid, profs in profiles_raw.items()
        }
        coordinator._sequence_rules = [r.to_dict() for r in updated]  # noqa: SLF001

    # Persist
    for eid, profs in coordinator._profiles.items():  # noqa: SLF001
        await storage.save_profile(hass, {"entity_id": eid, "profiles": profs})
    await storage.save_sequence_rules(
        hass, coordinator._sequence_rules  # noqa: SLF001
    )

    coordinator.profiles_loaded = len(coordinator._profiles)  # noqa: SLF001
    coordinator.profiles_ready = coordinator.profiles_loaded  # noqa: SLF001
    coordinator.sequence_rules_count = len(  # noqa: SLF001
        coordinator._sequence_rules  # noqa: SLF001
    )
    coordinator.last_training = datetime.now()  # noqa: SLF001

    _LOGGER.info(
        "Service train complete | entities=%d profiles=%d rules=%d",
        len(target_entities),
        coordinator.profiles_loaded,
        coordinator.sequence_rules_count,
    )

    return {
        "success": True,
        "entities_processed": len(target_entities),
        "profiles_loaded": coordinator.profiles_loaded,  # noqa: SLF001
        "rules_discovered": coordinator.sequence_rules_count,  # noqa: SLF001
    }


# ---------------------------------------------------------------------------
# Get Profile / List Rules
# ---------------------------------------------------------------------------


async def _handle_get_profile(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    """Handle we_are_home.get_profile service call.

    Returns learned profile with day groups, peak hours, and confidence.
    """
    entity_id = call.data["entity_id"]
    _LOGGER.info("Service call: get_profile | entity=%s", entity_id)

    profile_data = await storage.load_profile(hass, entity_id)
    if profile_data is None:
        _LOGGER.info("Service get_profile: entity=%s | NOT FOUND", entity_id)
        return {"entity_id": entity_id, "error": "No profile found"}

    profiles = profile_data.get("profiles", [profile_data])

    day_groups = {}
    max_confidence = 0.0
    total_observations = 0

    for profile in profiles:
        plist = profile.get("profiles", [profile])
        for p in (plist if isinstance(plist, list) else [plist]):
            day_group = p.get("day_group", "unknown")
            slots = p.get("slots", [])

            # Find peak hours (slots with p_on > 0.3)
            peak_hours = []
            for slot in slots:
                if slot.get("p_on", 0) > 0.3:
                    idx = slot.get("slot_index", 0)
                    hour = idx // 4
                    minute = (idx % 4) * 15
                    peak_hours.append(f"{hour:02d}:{minute:02d}")

            # Average on-probability across all slots
            avg_on = (
                sum(s.get("p_on", 0) for s in slots) / len(slots)
                if slots
                else 0
            )

            conf = p.get("confidence", 0)
            if conf > max_confidence:
                max_confidence = conf
            total_observations += p.get("total_observations", 0)

            day_groups[day_group] = {
                "peak_hours": _compress_time_ranges(peak_hours),
                "avg_on_probability": round(avg_on, 3),
            }

    # Get related sequence rules
    all_rules = await storage.load_sequence_rules(hass)
    as_source = [
        r.get("id")
        for r in all_rules
        if r.get("source_entity") == entity_id
    ]
    as_target = [
        r.get("id")
        for r in all_rules
        if r.get("target_entity") == entity_id
    ]

    result = {
        "entity_id": entity_id,
        "domain": entity_id.split(".", 1)[0],
        "confidence": round(max_confidence, 3),
        "day_groups": day_groups,
        "sequence_rules_as_source": as_source,
        "sequence_rules_as_target": as_target,
        "total_observations": total_observations,
        "last_updated": profile_data.get("last_updated"),
    }

    peak_summary = " | ".join(
        f"{dg}: {data['peak_hours']}"
        for dg, data in day_groups.items()
    ) if day_groups else "no peaks"
    _LOGGER.info(
        "Service get_profile: entity=%s | confidence=%.2f observations=%d "
        "rules_src=%d rules_tgt=%d | %s",
        entity_id,
        max_confidence,
        total_observations,
        len(as_source),
        len(as_target),
        peak_summary,
    )

    return result


async def _handle_list_rules(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    """Handle we_are_home.list_rules service call.

    Returns all discovered sequence rules with optional filters.
    """
    entity_filter = call.data.get("entity_id")
    min_conf = call.data.get("min_confidence", 0.0)
    _LOGGER.info(
        "Service call: list_rules | entity=%s min_conf=%.2f",
        entity_filter,
        min_conf,
    )

    rules = await storage.load_sequence_rules(hass)

    filtered = []
    for rule in rules:
        if min_conf and rule.get("confidence", 0) < min_conf:
            continue
        if entity_filter and (
            rule.get("source_entity") != entity_filter
            and rule.get("target_entity") != entity_filter
        ):
            continue

        filtered.append(
            {
                "id": rule.get("id"),
                "source": rule.get("source_entity"),
                "target": rule.get("target_entity"),
                "mean_delay_seconds": round(
                    rule.get("mean_delay", 0), 1
                ),
                "std_delay_seconds": round(
                    rule.get("std_delay", 0), 1
                ),
                "confidence": round(
                    rule.get("confidence", 0), 3
                ),
                "occurrences": rule.get("occurrence_count", 0),
            }
        )

    _LOGGER.info(
        "Service list_rules: found=%d filtered=%d",
        len(rules),
        len(filtered),
    )
    return {"rules": filtered, "total": len(filtered)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_coordinator(hass: HomeAssistant, switch_id: str | None) -> Any | None:
    """Find the appropriate coordinator for the given switch_id.

    For multi-instance support, uses the first configured instance if no
    switch_id is specified.
    """
    data = hass.data.get(DOMAIN, {})

    if not data:
        return None

    if switch_id:
        # Find coordinator by switch_id (entity_id format)
        for entry_id, entry_data in data.items():
            if switch_id.endswith(entry_id[:8]):
                return entry_data.get("coordinator")
        return None

    # Default: first available coordinator
    first_key = next(iter(data))
    return data[first_key].get("coordinator")


def _compress_time_ranges(times: list[str]) -> list[str]:
    """Compress consecutive time slots into ranges like '18:00-21:00'."""
    if not times:
        return []

    sorted_times = sorted(times)
    ranges: list[str] = []
    start = sorted_times[0]
    prev = start

    for current in sorted_times[1:]:
        # Check if consecutive 15-min slots
        sh, sm = int(start.split(":")[0]), int(start.split(":")[1])
        ch, cm = int(current.split(":")[0]), int(current.split(":")[1])
        ph, pm = int(prev.split(":")[0]), int(prev.split(":")[1])

        start_mins = sh * 60 + sm
        curr_mins = ch * 60 + cm
        prev_mins = ph * 60 + pm

        if curr_mins - prev_mins <= 15:
            prev = current
        else:
            ranges.append(f"{start}-{_next_slot(prev)}")
            start = current
            prev = current

    ranges.append(f"{start}-{_next_slot(sorted_times[-1])}")
    return ranges


def _next_slot(time_str: str) -> str:
    """Return the end of a 15-min slot."""
    h, m = int(time_str[:2]), int(time_str[3:])
    m += 15
    if m >= 60:
        h = (h + 1) % 24
        m = 0
    return f"{h:02d}:{m:02d}"
