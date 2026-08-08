"""pytest fixtures for We Are Home integration tests."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield


@pytest.fixture
def mock_recorder(hass, recorder_mock):
    """Set up recorder mock with default history retention."""
    yield recorder_mock


@pytest.fixture
def we_are_home_config():
    """Return a valid configuration for the integration."""
    return {
        "name": "We Are Home",
        "entities": [
            "light.sala",
            "light.cozinha",
            "switch.tv",
            "media_player.tv_sala",
        ],
        "learning_interval": 60,
        "simulation_interval": 30,
        "restore_states": True,
        "min_confidence": 0.3,
        "sequence_window": 60,
        "sequence_min_occurrences": 3,
        "boost_factor": 2.0,
    }
