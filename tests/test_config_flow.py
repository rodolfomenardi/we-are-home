"""Tests for the config and options flows."""

import logging

import pytest
import voluptuous as vol
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.we_are_home.config_flow import (
    WeAreHomeConfigFlow,
    WeAreHomeOptionsFlow,
)
from custom_components.we_are_home.const import (
    CONF_BOOST_FACTOR,
    CONF_ENTITIES,
    CONF_LEARNING_INTERVAL,
    DEFAULT_NAME,
    DOMAIN,
)


def make_flow(hass) -> WeAreHomeConfigFlow:
    """Instantiate the user config flow with hass attached."""
    flow = WeAreHomeConfigFlow()
    flow.hass = hass
    return flow


def marker_defaults(schema: vol.Schema) -> dict:
    """Map field names to their schema defaults.

    Mutable defaults (lists) become default_factory lambdas; resolve them.
    """
    return {
        key.schema: key.default() if callable(key.default) else key.default
        for key in schema.schema
        if isinstance(key, vol.Marker)
    }


# ---------------------------------------------------------------------------
# User flow
# ---------------------------------------------------------------------------


async def test_user_flow_shows_form(hass):
    """First step with no input shows the form."""
    result = await make_flow(hass).async_step_user(user_input=None)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_creates_entry(hass):
    """Valid input creates an entry with default title."""
    result = await make_flow(hass).async_step_user(
        user_input={CONF_ENTITIES: ["light.sala"]}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["data"] == {CONF_ENTITIES: ["light.sala"]}


async def test_user_flow_custom_title(hass):
    """A name in the input becomes the entry title."""
    result = await make_flow(hass).async_step_user(
        user_input={CONF_ENTITIES: ["light.sala"], "name": "Minha Casa"}
    )
    assert result["title"] == "Minha Casa"


async def test_user_flow_no_entities_error(hass):
    """Empty entity list is rejected with no_entities."""
    result = await make_flow(hass).async_step_user(user_input={"name": "Casa"})
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_ENTITIES: "no_entities"}


async def test_user_flow_schema_defaults(hass):
    """The schema carries sensible defaults."""
    result = await make_flow(hass).async_step_user(user_input=None)
    defaults = marker_defaults(result["data_schema"])
    assert defaults[CONF_ENTITIES] == []
    assert defaults[CONF_LEARNING_INTERVAL] == 60
    assert defaults[CONF_BOOST_FACTOR] == 2.0


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


def make_options_flow(hass, entry) -> WeAreHomeOptionsFlow:
    """Instantiate the options flow with hass attached."""
    flow = WeAreHomeOptionsFlow(entry)
    flow.hass = hass
    return flow


async def test_options_flow_shows_form_with_defaults(hass):
    """The options form defaults merge entry data and options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENTITIES: ["light.a"], CONF_LEARNING_INTERVAL: 30},
        options={CONF_ENTITIES: ["light.b"]},
    )
    result = await make_options_flow(hass, entry).async_step_init(user_input=None)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"
    defaults = marker_defaults(result["data_schema"])
    # options override data; defaults fill the rest
    assert defaults[CONF_ENTITIES] == ["light.b"]
    assert defaults[CONF_LEARNING_INTERVAL] == 30
    assert defaults[CONF_BOOST_FACTOR] == 2.0


async def test_options_flow_creates_entry(hass):
    """Valid options update are accepted."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_ENTITIES: ["light.a"]}
    )
    result = await make_options_flow(hass, entry).async_step_init(
        user_input={CONF_ENTITIES: ["switch.tv"]}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ENTITIES: ["switch.tv"]}


async def test_options_flow_no_entities_error(hass):
    """Empty entity list is rejected in options too."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_ENTITIES: ["light.a"]})
    result = await make_options_flow(hass, entry).async_step_init(
        user_input={CONF_ENTITIES: []}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_ENTITIES: "no_entities"}


async def test_options_flow_removed_entities_logged(hass, caplog):
    """Removing entities logs the exclusion without failing."""
    caplog.set_level(logging.INFO, logger="custom_components.we_are_home.config_flow")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENTITIES: ["light.a", "light.b", "switch.tv"]},
    )
    result = await make_options_flow(hass, entry).async_step_init(
        user_input={CONF_ENTITIES: ["light.a"]}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert "Entities removed from config" in caplog.text
    assert "light.b" in caplog.text and "switch.tv" in caplog.text


def test_get_options_flow_returns_options_flow():
    """async_get_options_flow returns a WeAreHomeOptionsFlow."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    flow = WeAreHomeConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, WeAreHomeOptionsFlow)
