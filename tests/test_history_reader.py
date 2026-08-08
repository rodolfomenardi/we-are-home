"""Tests for the recorder history reader."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.we_are_home import history_reader


def state_obj(
    entity_id: str,
    state: str,
    last_changed: datetime,
    attributes: dict | None = None,
) -> SimpleNamespace:
    """Build a recorder state double."""
    return SimpleNamespace(
        entity_id=entity_id,
        state=state,
        last_changed=last_changed,
        last_updated=last_changed,
        attributes=attributes or {},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_is_supported_entity():
    """Supported domains pass; sensor entities are excluded."""
    assert history_reader._is_supported_entity("light.sala")  # noqa: SLF001
    assert history_reader._is_supported_entity("switch.tv")  # noqa: SLF001
    assert not history_reader._is_supported_entity("sensor.temp")  # noqa: SLF001


def test_state_change_to_dict_converts():
    """Recorder states become plain dicts."""
    ts = datetime(2026, 8, 3, 18, 0)
    change = state_obj("light.sala", "on", ts, {"brightness": 200})
    out = history_reader._state_change_to_dict(change)  # noqa: SLF001
    assert out["entity_id"] == "light.sala"
    assert out["state"] == "on"
    assert out["last_changed"] == "2026-08-03T18:00:00"
    assert out["attributes"] == {"brightness": 200}


def test_state_change_to_dict_filters_unavailable():
    """unavailable/unknown states are dropped."""
    ts = datetime(2026, 8, 3, 18, 0)
    assert (
        history_reader._state_change_to_dict(state_obj("light.sala", "unavailable", ts))  # noqa: SLF001
        is None
    )
    assert (
        history_reader._state_change_to_dict(state_obj("light.sala", "unknown", ts))  # noqa: SLF001
        is None
    )


def test_state_change_to_dict_missing_fields():
    """Missing state or last_changed yields None."""
    ts = datetime(2026, 8, 3, 18, 0)
    assert history_reader._state_change_to_dict(SimpleNamespace()) is None  # noqa: SLF001
    no_ts = SimpleNamespace(state="on", entity_id="light.sala")
    assert history_reader._state_change_to_dict(no_ts) is None  # noqa: SLF001


def test_state_change_to_dict_string_timestamp():
    """Non-datetime timestamps are stringified."""
    change = SimpleNamespace(
        entity_id="light.sala", state="on", last_changed="2026-08-03T18:00:00"
    )
    out = history_reader._state_change_to_dict(change)  # noqa: SLF001
    assert out["last_changed"] == "2026-08-03T18:00:00"


def test_filter_transient_removes_quick_flips():
    """Changes lasting under 5 seconds collapse into one."""
    changes = [
        {"last_changed": "2026-08-03T18:00:00", "state": "on"},
        {"last_changed": "2026-08-03T18:00:03", "state": "off"},
        {"last_changed": "2026-08-03T18:00:10", "state": "on"},
    ]
    kept = history_reader._filter_transient(changes)
    assert len(kept) == 2
    assert kept[0] == changes[1]  # transient replaced by the longer state
    assert kept[1] == changes[2]


def test_filter_transient_keeps_slow_changes():
    """Changes spanning the minimum duration are all kept."""
    changes = [
        {"last_changed": "2026-08-03T18:00:00", "state": "on"},
        {"last_changed": "2026-08-03T18:10:00", "state": "off"},
    ]
    assert history_reader._filter_transient(changes) == changes


def test_filter_transient_invalid_timestamps():
    """Unparseable timestamps pass through."""
    changes = [{"last_changed": "garbage", "state": "on"}]
    assert history_reader._filter_transient(changes) == changes


# ---------------------------------------------------------------------------
# History queries
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_history(monkeypatch):
    """Patch history.get_significant_states."""

    def _patch(return_value):
        if isinstance(return_value, Exception):
            def _raise(*a, **k):
                raise return_value

            monkeypatch.setattr(
                history_reader.history, "get_significant_states", _raise
            )
        else:
            monkeypatch.setattr(
                history_reader.history,
                "get_significant_states",
                lambda *a, **k: return_value,
            )

    return _patch


async def test_get_multi_entity_history(hass, patch_history):
    """Supported entities are returned as change dicts."""
    ts = datetime(2026, 8, 3, 18, 0)
    patch_history(
        {
            "light.a": [
                state_obj("light.a", "on", ts),
                state_obj("light.a", "off", ts + timedelta(minutes=10)),
            ],
            "sensor.temp": [state_obj("sensor.temp", "21.5", ts)],
        }
    )
    result = await history_reader.get_multi_entity_history(hass, ["light.a", "sensor.temp"])
    assert set(result) == {"light.a"}
    assert result["light.a"][0]["state"] == "on"


async def test_get_multi_entity_history_empty(hass):
    """No entities requested yields an empty dict."""
    assert await history_reader.get_multi_entity_history(hass, []) == {}


async def test_get_multi_entity_history_handles_query_error(hass, patch_history):
    """Recorder errors degrade to an empty dict."""
    patch_history(RuntimeError("db locked"))
    result = await history_reader.get_multi_entity_history(hass, ["light.a"])
    assert result == {}


async def test_get_entity_history_delegates(hass, patch_history):
    """Single-entity query delegates to the multi-entity one."""
    ts = datetime(2026, 8, 3, 18, 0)
    patch_history({"light.a": [state_obj("light.a", "on", ts)]})
    result = await history_reader.get_entity_history(hass, "light.a")
    assert result == [
        {
            "entity_id": "light.a",
            "state": "on",
            "attributes": {},
            "last_changed": "2026-08-03T18:00:00",
            "last_updated": "2026-08-03T18:00:00",
        }
    ]


async def test_get_entity_states_at_time(hass, patch_history):
    """States at a timestamp come from the last state of each entity."""
    ts = datetime(2026, 8, 3, 18, 0)
    patch_history(
        {
            "light.a": [
                state_obj("light.a", "off", ts - timedelta(minutes=5)),
                state_obj("light.a", "on", ts),
            ],
            "switch.tv": [],
        }
    )
    result = await history_reader.get_entity_states_at_time(hass, ["light.a", "switch.tv"], ts)
    assert result == {"light.a": "on", "switch.tv": "off"}


async def test_get_entity_states_at_time_error(hass, patch_history):
    """Query errors degrade to an empty dict."""
    patch_history(RuntimeError("db locked"))
    result = await history_reader.get_entity_states_at_time(
        hass, ["light.a"], datetime(2026, 8, 3, 18, 0)
    )
    assert result == {}


async def test_get_recent_state_changes(hass, patch_history):
    """Recent changes filter unsupported entities and transients."""
    ts = datetime(2026, 8, 3, 8, 0)
    patch_history(
        {
            "light.a": [
                state_obj("light.a", "on", ts),
                state_obj("light.a", "off", ts + timedelta(seconds=2)),
                state_obj("light.a", "on", ts + timedelta(minutes=1)),
            ],
            "sensor.temp": [state_obj("sensor.temp", "21.5", ts)],
        }
    )
    result = await history_reader.get_recent_state_changes(
        hass, ["light.a", "sensor.temp"], ts - timedelta(minutes=5)
    )
    assert set(result) == {"light.a"}
    # transient flip collapsed
    assert len(result["light.a"]) == 2
    assert result["light.a"][0]["state"] == "off"


async def test_get_recent_state_changes_empty(hass):
    """No entities requested yields an empty dict."""
    assert await history_reader.get_recent_state_changes(hass, [], datetime.now()) == {}


# ---------------------------------------------------------------------------
# Recorder info
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_recorder(monkeypatch):
    """Patch recorder.get_instance."""

    def _patch(instance):
        monkeypatch.setattr(
            history_reader.recorder, "get_instance", lambda hass: instance
        )

    return _patch


async def test_get_recorder_info(hass, fake_recorder):
    """Recorder engine, backlog, and run history are reported."""
    fake_recorder(
        SimpleNamespace(
            engine="sqlite",
            backlog=3,
            recording=True,
            max_backlog=100,
            db=SimpleNamespace(
                run_history=SimpleNamespace(get_run_ids=lambda: [1, 2, 3])
            ),
        )
    )
    info = await history_reader.get_recorder_info(hass)
    assert info["engine"] == "sqlite"
    assert info["backlog"] == 3
    assert info["recording"] is True
    assert info["runs"] == 3


async def test_get_recorder_info_without_db(hass, fake_recorder):
    """Recorders without db info still report basics."""
    fake_recorder(SimpleNamespace(engine="mysql", backlog=0, recording=False, max_backlog=0))
    info = await history_reader.get_recorder_info(hass)
    assert info["engine"] == "mysql"
    assert "runs" not in info


async def test_get_recorder_info_error(hass, monkeypatch):
    """get_instance failures degrade gracefully."""

    def _raise(hass):
        raise RuntimeError("no recorder")

    monkeypatch.setattr(history_reader.recorder, "get_instance", _raise)
    info = await history_reader.get_recorder_info(hass)
    assert info["engine"] == "unknown"
    assert "error" in info
