"""JSON persistence layer for We Are Home integration.

Stores learned profiles, sequence rules, entity configs, and learning
run logs under Home Assistant's .storage/we_are_home/ directory.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .const import STORAGE_DIR, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

STORAGE_SUBDIR = "we_are_home"


def _sanitize_filename(entity_id: str) -> str:
    """Convert entity_id to a safe filename."""
    return entity_id.replace(".", "_") + ".json"


async def ensure_storage_dir(hass: HomeAssistant) -> str:
    """Create storage directory and profiles subdirectory if needed.

    Returns the path to the integration's storage directory.
    """
    base = hass.config.path(STORAGE_DIR, STORAGE_SUBDIR)
    profiles_dir = os.path.join(base, "profiles")

    def _ensure() -> str:
        os.makedirs(base, exist_ok=True)
        os.makedirs(profiles_dir, exist_ok=True)
        return base

    return await hass.async_add_executor_job(_ensure)


async def _read_json(hass: HomeAssistant, relative_path: str) -> Any | None:
    """Read a JSON file from the storage directory, returning None if not found."""
    base = await ensure_storage_dir(hass)
    filepath = os.path.join(base, relative_path)

    def _read() -> Any | None:
        if not os.path.exists(filepath):
            return None
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)

    try:
        return await hass.async_add_executor_job(_read)
    except (json.JSONDecodeError, OSError) as exc:
        _LOGGER.warning("Failed to read %s: %s", filepath, exc)
        return None


async def _write_json(
    hass: HomeAssistant, relative_path: str, data: Any
) -> None:
    """Write data as JSON to the storage directory."""
    base = await ensure_storage_dir(hass)
    filepath = os.path.join(base, relative_path)

    def _write() -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)

    try:
        await hass.async_add_executor_job(_write)
    except OSError as exc:
        _LOGGER.error("Failed to write %s: %s", filepath, exc)


# ---------------------------------------------------------------------------
# Entity Configs
# ---------------------------------------------------------------------------


async def load_configs(hass: HomeAssistant) -> list[dict]:
    """Load entity configs from storage/config.json.

    Returns empty list if the file does not exist.
    """
    data = await _read_json(hass, "config.json")
    if data is None:
        return []
    if isinstance(data, dict) and "entities" in data:
        return data["entities"]
    return []


async def save_configs(
    hass: HomeAssistant, configs: list[dict]
) -> None:
    """Save entity configs to storage/config.json."""
    await _write_json(
        hass,
        "config.json",
        {"version": STORAGE_VERSION, "entities": configs},
    )


# ---------------------------------------------------------------------------
# Time Profiles
# ---------------------------------------------------------------------------


async def load_profile(hass: HomeAssistant, entity_id: str) -> dict | None:
    """Load a single entity profile.

    Returns None if the profile file does not exist.
    """
    filename = _sanitize_filename(entity_id)
    return await _read_json(hass, f"profiles/{filename}")


async def save_profile(hass: HomeAssistant, profile: dict) -> None:
    """Save a profile to storage."""
    entity_id = profile.get("entity_id", "unknown")
    filename = _sanitize_filename(entity_id)
    await _write_json(hass, f"profiles/{filename}", profile)


async def load_all_profiles(hass: HomeAssistant) -> dict[str, dict]:
    """Load all profiles from storage/profiles/.

    Returns dict keyed by entity_id.
    """
    base = await ensure_storage_dir(hass)
    profiles_dir = os.path.join(base, "profiles")

    def _load_all() -> dict[str, dict]:
        result = {}
        if not os.path.isdir(profiles_dir):
            return result
        for filename in sorted(os.listdir(profiles_dir)):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(profiles_dir, filename)
            try:
                with open(filepath, encoding="utf-8") as f:
                    profile = json.load(f)
                entity_id = profile.get("entity_id", filename[:-5].replace("_", "."))
                result[entity_id] = profile
            except (json.JSONDecodeError, OSError) as exc:
                _LOGGER.warning(
                    "Skipping corrupted profile %s: %s", filepath, exc
                )
        return result

    return await hass.async_add_executor_job(_load_all)


# ---------------------------------------------------------------------------
# Sequence Rules
# ---------------------------------------------------------------------------


async def load_sequence_rules(hass: HomeAssistant) -> list[dict]:
    """Load all sequence rules from storage/sequence_rules.json."""
    data = await _read_json(hass, "sequence_rules.json")
    if data is None:
        return []
    if isinstance(data, dict) and "rules" in data:
        return data["rules"]
    return []


async def save_sequence_rules(
    hass: HomeAssistant, rules: list[dict]
) -> None:
    """Save sequence rules to storage/sequence_rules.json."""
    await _write_json(
        hass,
        "sequence_rules.json",
        {"version": STORAGE_VERSION, "rules": rules},
    )


# ---------------------------------------------------------------------------
# Learning Log
# ---------------------------------------------------------------------------

_DEFAULT_MAX_LOG_ENTRIES = 50


async def load_learning_log(
    hass: HomeAssistant, max_entries: int = _DEFAULT_MAX_LOG_ENTRIES
) -> list[dict]:
    """Load the last N learning run records."""
    data = await _read_json(hass, "learning_log.json")
    if data is None:
        return []
    if isinstance(data, list):
        return data[-max_entries:]
    return []


async def append_learning_run(
    hass: HomeAssistant,
    run: dict,
    max_entries: int = _DEFAULT_MAX_LOG_ENTRIES,
) -> None:
    """Append a learning run to the rolling log.

    Keeps only the last max_entries records.
    """
    existing = await load_learning_log(hass, max_entries=0)  # load all
    existing.append(run)
    trimmed = existing[-max_entries:]
    await _write_json(hass, "learning_log.json", trimmed)
