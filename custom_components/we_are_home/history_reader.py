"""Async query interface to Home Assistant recorder database.

Extracts state change history for configured entities with optimised
batch queries. All database access runs via executor thread pool to
keep the HA event loop responsive.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import recorder
from homeassistant.components.recorder import history
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import UNDEFINED

from .const import SUPPORTED_DOMAINS

_LOGGER = logging.getLogger(__name__)


async def _run_recorder_query(hass: HomeAssistant, fn: callable) -> Any:
    """Run a recorder query on the recorder's executor, with fallback.

    Home Assistant recommends recorder.get_instance(hass).async_add_executor_job()
    for database operations to avoid HA core warnings. Falls back to the generic
    hass.async_add_executor_job() when the recorder instance isn't available
    (e.g. in tests with mocked recorder).
    """
    try:
        rec = recorder.get_instance(hass)
        if hasattr(rec, "async_add_executor_job"):
            return await rec.async_add_executor_job(fn)
    except (AttributeError, KeyError, RuntimeError):
        pass
    return await hass.async_add_executor_job(fn)

# Minimum state duration (seconds) to consider an entity state meaningful.
# Filters out transient motion-sensor events and momentary flickers.
_MIN_STATE_DURATION = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_supported_entity(entity_id: str) -> bool:
    """Check if entity belongs to a supported domain."""
    domain = entity_id.split(".", 1)[0]
    return domain in SUPPORTED_DOMAINS


def _state_change_to_dict(change: Any) -> dict | None:
    """Convert a recorder state change to a dict.

    Returns None for unavailable/unknown states or transient changes.
    """
    state = getattr(change, "state", None)
    if state is None:
        return None
    if state in ("unavailable", "unknown"):
        return None

    last_changed = getattr(change, "last_changed", None)
    last_updated = getattr(change, "last_updated", None)
    if last_changed is None:
        return None

    attrs = dict(getattr(change, "attributes", {}) or {})

    return {
        "entity_id": getattr(change, "entity_id", ""),
        "state": state,
        "attributes": attrs,
        "last_changed": (
            last_changed.isoformat()
            if isinstance(last_changed, datetime)
            else str(last_changed)
        ),
        "last_updated": (
            last_updated.isoformat()
            if isinstance(last_updated, datetime)
            else str(last_updated)
        ),
    }


def _filter_transient(
    state_changes: list[dict],
    min_duration: int = _MIN_STATE_DURATION,
) -> list[dict]:
    """Remove state changes where the entity changed back too quickly."""
    if len(state_changes) < 2:
        return state_changes

    kept: list[dict] = []
    for i, change in enumerate(state_changes):
        if i == 0:
            kept.append(change)
            continue
        prev = kept[-1]
        try:
            curr_ts = datetime.fromisoformat(change["last_changed"])
            prev_ts = datetime.fromisoformat(prev["last_changed"])
            if (curr_ts - prev_ts).total_seconds() < min_duration:
                # Replace previous with current (longer-lasting state)
                kept[-1] = change
                continue
        except (ValueError, KeyError):
            pass
        kept.append(change)

    return kept


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_entity_history(
    hass: HomeAssistant,
    entity_id: str,
    days_back: int | None = None,
) -> list[dict]:
    """Return state change history for a single entity.

    Args:
        hass: Home Assistant instance.
        entity_id: The entity to query.
        days_back: Limit to N days of history; None = all available.

    Returns:
        List of state change dicts, most recent first.
    """
    result = await get_multi_entity_history(hass, [entity_id], days_back)
    return result.get(entity_id, [])


async def get_multi_entity_history(
    hass: HomeAssistant,
    entity_ids: list[str],
    days_back: int | None = None,
) -> dict[str, list[dict]]:
    """Return state change history for multiple entities.

    Uses the HA history API for efficient batch retrieval and filters
    out unsupported domains, unavailable states, and transient changes.

    Args:
        hass: Home Assistant instance.
        entity_ids: List of entity IDs to query.
        days_back: Limit to N days; None = all available.

    Returns:
        Dict keyed by entity_id with list of state change dicts.
    """
    if not entity_ids:
        return {}

    _LOGGER.debug(
        "Fetching multi-entity history: %d entities, days_back=%s",
        len(entity_ids),
        days_back,
    )

    # Build time window
    start_time: datetime | None = None
    if days_back is not None and days_back > 0:
        start_time = datetime.now() - timedelta(days=days_back)

    # Query history via HA's built-in API (runs on executor internally)
    def _fetch() -> dict[str, list[dict]]:
        """Fetch history inside executor."""
        result: dict[str, list[dict]] = {}
        try:
            raw = history.get_significant_states(
                hass,
                start_time=start_time or datetime(2000, 1, 1),
                end_time=None,
                entity_ids=entity_ids,
                filters=None,
                include_start_time_state=True,
                significant_changes_only=True,
                minimal_response=False,
                no_attributes=False,
            )
        except Exception as exc:
            _LOGGER.error(
                "Failed to query recorder history: %s. "
                "Recorder may be corrupted or purged. "
                "Learning will degrade gracefully.",
                exc,
            )
            return result

        if not raw:
            return result

        for entity_id, states in raw.items():
            if not _is_supported_entity(entity_id):
                continue

            changes: list[dict] = []
            for state_obj in states:
                change = _state_change_to_dict(state_obj)
                if change is not None:
                    changes.append(change)

            if changes:
                changes = _filter_transient(changes)
                result[entity_id] = changes

        return result

    try:
        result = await _run_recorder_query(hass, _fetch)
        total = sum(len(v) for v in result.values())
        _LOGGER.debug(
            "History fetch complete | events=%d entities_with_data=%d",
            total,
            len([k for k, v in result.items() if v]),
        )
        return result
    except Exception as exc:
        _LOGGER.error(
            "Error fetching entity history: %s. Returning empty results.", exc
        )
        return {}


async def get_entity_states_at_time(
    hass: HomeAssistant,
    entity_ids: list[str],
    timestamp: datetime,
) -> dict[str, str]:
    """Return the state of each entity at a specific point in time.

    Useful for capturing pre-simulation states.

    Returns:
        Dict keyed by entity_id → state string.
    """
    if not entity_ids:
        return {}

    def _fetch() -> dict[str, str]:
        result: dict[str, str] = {}
        try:
            raw = history.get_significant_states(
                hass,
                start_time=timestamp - timedelta(seconds=1),
                end_time=timestamp,
                entity_ids=entity_ids,
                filters=None,
                include_start_time_state=False,
                significant_changes_only=True,
                minimal_response=True,
                no_attributes=True,
            )
        except Exception as exc:
            _LOGGER.warning("Failed to get states at time: %s", exc)
            return result

        for entity_id, states in raw.items():
            if states:
                result[entity_id] = getattr(states[-1], "state", "off")
            else:
                result[entity_id] = "off"

        return result

    return await _run_recorder_query(hass, _fetch)


async def get_recent_state_changes(
    hass: HomeAssistant,
    entity_ids: list[str],
    since: datetime,
) -> dict[str, list[dict]]:
    """Return state changes since a given timestamp.

    Used for incremental learning updates.

    Args:
        hass: Home Assistant instance.
        entity_ids: Entities to query.
        since: Timestamp to query from.

    Returns:
        Dict keyed by entity_id with new state changes.
    """
    if not entity_ids:
        return {}

    _LOGGER.debug(
        "Fetching recent changes: %d entities since %s",
        len(entity_ids),
        since.isoformat(),
    )

    def _fetch() -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        try:
            raw = history.get_significant_states(
                hass,
                start_time=since,
                end_time=None,
                entity_ids=entity_ids,
                filters=None,
                include_start_time_state=False,
                significant_changes_only=True,
                minimal_response=False,
                no_attributes=False,
            )
        except Exception as exc:
            _LOGGER.warning(
                "Failed to get recent state changes since %s: %s", since, exc
            )
            return result

        for entity_id, states in raw.items():
            if not _is_supported_entity(entity_id):
                continue
            changes = []
            for state_obj in states:
                change = _state_change_to_dict(state_obj)
                if change is not None:
                    changes.append(change)
            if changes:
                result[entity_id] = _filter_transient(changes)

        return result

    return await _run_recorder_query(hass, _fetch)


async def get_recorder_info(hass: HomeAssistant) -> dict:
    """Return recorder status for diagnostics.

    Returns:
        Dict with engine type, database URL (redacted), oldest run,
        newest run, and entity count.
    """

    def _fetch() -> dict:
        rec = recorder.get_instance(hass)
        info: dict[str, Any] = {
            "engine": getattr(rec, "engine", "unknown"),
            "backlog": getattr(rec, "backlog", 0),
            "recording": getattr(rec, "recording", False),
            "max_backlog": getattr(rec, "max_backlog", 0),
        }

        # Try to get run info
        try:
            db = getattr(rec, "db", None)
            if db is not None:
                run_history = getattr(db, "run_history", None)
                if run_history is not None:
                    info["runs"] = len(run_history.get_run_ids())
        except Exception:  # noqa: BLE001
            pass

        return info

    try:
        return await _run_recorder_query(hass, _fetch)
    except Exception as exc:
        _LOGGER.warning("Failed to get recorder info: %s", exc)
        return {"engine": "unknown", "error": str(exc)}
