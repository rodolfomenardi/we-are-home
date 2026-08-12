"""Tests for the JSON persistence layer."""

import json
import os

import pytest

from custom_components.we_are_home import storage
from custom_components.we_are_home.const import STORAGE_DIR, STORAGE_VERSION


@pytest.fixture
def isolated_hass(hass, tmp_path):
    """Point the hass config dir at a per-test temp directory.

    The phcc `hass` fixture shares one config dir across all tests, which
    would leak storage files between tests.
    """
    hass.config.config_dir = str(tmp_path)
    return hass


def storage_path(isolated_hass, *parts) -> str:
    """Absolute path inside the integration storage dir."""
    return os.path.join(isolated_hass.config.path(STORAGE_DIR), "we_are_home", *parts)


async def test_ensure_storage_dir_creates_directories(isolated_hass):
    """ensure_storage_dir creates base and profiles dirs."""
    base = await storage.ensure_storage_dir(isolated_hass)
    assert os.path.isdir(base)
    assert os.path.isdir(os.path.join(base, "profiles"))
    assert base == storage_path(isolated_hass)


async def test_sanitize_filename():
    """Entity ids become safe filenames."""
    assert storage._sanitize_filename("light.sala") == "light_sala.json"  # noqa: SLF001


async def test_save_and_load_configs(isolated_hass):
    """Configs roundtrip through config.json."""
    configs = [{"entity_id": "light.sala", "enabled": True}]
    await storage.save_configs(isolated_hass, configs)
    assert await storage.load_configs(isolated_hass) == configs


async def test_load_configs_missing_file(isolated_hass):
    """Missing config.json yields an empty list."""
    assert await storage.load_configs(isolated_hass) == []


async def test_load_configs_wrong_shape(isolated_hass):
    """A config.json without an entities key yields an empty list."""
    await storage._write_json(isolated_hass, "config.json", {"version": 1})  # noqa: SLF001
    assert await storage.load_configs(isolated_hass) == []


async def test_save_and_load_profile(isolated_hass):
    """Profiles roundtrip through profiles/<entity>.json."""
    profile = {"entity_id": "light.sala", "confidence": 0.7, "slots": []}
    await storage.save_profile(isolated_hass, profile)
    loaded = await storage.load_profile(isolated_hass, "light.sala")
    assert loaded == profile


async def test_load_profile_missing_file(isolated_hass):
    """Missing profile files yield None."""
    assert await storage.load_profile(isolated_hass, "light.sala") is None


async def test_delete_profile(isolated_hass):
    """delete_profile removes the entity's profile file."""
    profile = {"entity_id": "light.sala", "confidence": 0.7, "slots": []}
    await storage.save_profile(isolated_hass, profile)
    assert await storage.load_profile(isolated_hass, "light.sala") == profile
    await storage.delete_profile(isolated_hass, "light.sala")
    assert await storage.load_profile(isolated_hass, "light.sala") is None


async def test_delete_profile_missing_is_noop(isolated_hass):
    """Deleting a nonexistent profile does not raise."""
    await storage.delete_profile(isolated_hass, "light.inexistente")


async def test_load_all_profiles_empty(isolated_hass):
    """An empty profiles dir yields an empty dict."""
    assert await storage.load_all_profiles(isolated_hass) == {}


async def test_load_all_profiles_keys_by_entity(isolated_hass):
    """Profiles are keyed by their entity_id."""
    await storage.save_profile(isolated_hass, {"entity_id": "light.sala", "slots": []})
    await storage.save_profile(isolated_hass, {"entity_id": "switch.tv", "slots": []})
    loaded = await storage.load_all_profiles(isolated_hass)
    assert set(loaded) == {"light.sala", "switch.tv"}


async def test_load_all_profiles_skips_corrupted(isolated_hass):
    """Corrupted JSON files are skipped with a warning."""
    await storage.ensure_storage_dir(isolated_hass)
    good = storage_path(isolated_hass, "profiles", "light_sala.json")
    bad = storage_path(isolated_hass, "profiles", "switch_tv.json")
    with open(good, "w", encoding="utf-8") as f:
        json.dump({"entity_id": "light.sala", "slots": []}, f)
    with open(bad, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    loaded = await storage.load_all_profiles(isolated_hass)
    assert loaded == {"light.sala": {"entity_id": "light.sala", "slots": []}}


async def test_save_and_load_sequence_rules(isolated_hass):
    """Sequence rules roundtrip through sequence_rules.json."""
    rules = [{"id": "a→b", "confidence": 0.9}]
    await storage.save_sequence_rules(isolated_hass, rules)
    assert await storage.load_sequence_rules(isolated_hass) == rules


async def test_load_sequence_rules_missing_file(isolated_hass):
    """Missing sequence_rules.json yields an empty list."""
    assert await storage.load_sequence_rules(isolated_hass) == []


async def test_load_sequence_rules_wrong_shape(isolated_hass):
    """A file without a rules key yields an empty list."""
    await storage._write_json(isolated_hass, "sequence_rules.json", {"nope": 1})  # noqa: SLF001
    assert await storage.load_sequence_rules(isolated_hass) == []


async def test_append_and_load_learning_log(isolated_hass):
    """Learning runs append and trim to max_entries."""
    for i in range(60):
        await storage.append_learning_run(isolated_hass, {"run": i}, max_entries=50)
    log = await storage.load_learning_log(isolated_hass, max_entries=50)
    assert len(log) == 50
    assert log[-1] == {"run": 59}
    assert log[0] == {"run": 10}


async def test_load_learning_log_missing_file(isolated_hass):
    """Missing learning_log.json yields an empty list."""
    assert await storage.load_learning_log(isolated_hass) == []


async def test_load_learning_log_wrong_shape(isolated_hass):
    """A non-list learning log yields an empty list."""
    await storage._write_json(isolated_hass, "learning_log.json", {"x": 1})  # noqa: SLF001
    assert await storage.load_learning_log(isolated_hass) == []


async def test_read_json_corrupted_returns_none(isolated_hass):
    """Corrupted JSON reads return None with a warning."""
    await storage.ensure_storage_dir(isolated_hass)
    path = storage_path(isolated_hass, "corrupt.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{nope")
    assert await storage._read_json(isolated_hass, "corrupt.json") is None  # noqa: SLF001


async def test_write_json_handles_os_error(isolated_hass, monkeypatch):
    """OSError during writes is logged, not raised."""
    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(json, "dump", _boom)
    await storage._write_json(  # noqa: SLF001
        isolated_hass, "config.json", {"entities": []}
    )


async def test_save_configs_writes_version(isolated_hass):
    """Saved configs carry the storage version."""
    await storage.save_configs(isolated_hass, [])
    path = storage_path(isolated_hass, "config.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == STORAGE_VERSION
    assert data["entities"] == []
