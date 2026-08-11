"""Configuration flow for We Are Home integration.

Provides a UI config flow (ConfigFlow) for initial setup and an
OptionsFlow for reconfiguring an existing integration instance.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_BOOST_FACTOR,
    CONF_ENTITIES,
    CONF_LEARNING_INTERVAL,
    CONF_MIN_CONFIDENCE,
    CONF_RANDOM_SEED,
    CONF_RESTORE_STATES,
    CONF_SEQUENCE_MIN_OCCURRENCES,
    CONF_SEQUENCE_WINDOW,
    CONF_SIMULATION_INTERVAL,
    DEFAULT_BOOST_FACTOR,
    DEFAULT_LEARNING_INTERVAL,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_NAME,
    DEFAULT_RANDOM_SEED,
    DEFAULT_RESTORE_STATES,
    DEFAULT_SEQUENCE_MIN_OCCURRENCES,
    DEFAULT_SEQUENCE_WINDOW,
    DEFAULT_SIMULATION_INTERVAL,
    DOMAIN,
    SUPPORTED_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)

# Schema shared by user setup and options flow
_ENTITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=SUPPORTED_DOMAINS, multiple=True)
)


def _build_data_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the data schema for config/options flow."""
    if defaults is None:
        defaults = {}

    return vol.Schema(
        {
            vol.Required(
                CONF_ENTITIES,
                default=defaults.get(CONF_ENTITIES, []),
            ): _ENTITY_SELECTOR,
            vol.Optional(
                CONF_LEARNING_INTERVAL,
                default=defaults.get(
                    CONF_LEARNING_INTERVAL, DEFAULT_LEARNING_INTERVAL
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440)),
            vol.Optional(
                CONF_SIMULATION_INTERVAL,
                default=defaults.get(
                    CONF_SIMULATION_INTERVAL, DEFAULT_SIMULATION_INTERVAL
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            vol.Optional(
                CONF_RESTORE_STATES,
                default=defaults.get(
                    CONF_RESTORE_STATES, DEFAULT_RESTORE_STATES
                ),
            ): bool,
            vol.Optional(
                CONF_MIN_CONFIDENCE,
                default=defaults.get(
                    CONF_MIN_CONFIDENCE, DEFAULT_MIN_CONFIDENCE
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                CONF_SEQUENCE_WINDOW,
                default=defaults.get(
                    CONF_SEQUENCE_WINDOW, DEFAULT_SEQUENCE_WINDOW
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=15, max=360)),
            vol.Optional(
                CONF_SEQUENCE_MIN_OCCURRENCES,
                default=defaults.get(
                    CONF_SEQUENCE_MIN_OCCURRENCES,
                    DEFAULT_SEQUENCE_MIN_OCCURRENCES,
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=50)),
            vol.Optional(
                CONF_BOOST_FACTOR,
                default=defaults.get(
                    CONF_BOOST_FACTOR, DEFAULT_BOOST_FACTOR
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=10.0)),
            vol.Optional(
                CONF_RANDOM_SEED,
                default=defaults.get(CONF_RANDOM_SEED, DEFAULT_RANDOM_SEED),
            ): vol.Maybe(int),
        }
    )


class WeAreHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for We Are Home."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entities = user_input.get(CONF_ENTITIES, [])
            if not entities:
                errors[CONF_ENTITIES] = "no_entities"

            if not errors:
                return self.async_create_entry(
                    title=user_input.get("name", DEFAULT_NAME),
                    data=user_input,
                )

        schema = _build_data_schema()
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return WeAreHomeOptionsFlow(config_entry)


class WeAreHomeOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for reconfiguring a We Are Home instance."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entities = user_input.get(CONF_ENTITIES, [])
            if not entities:
                errors[CONF_ENTITIES] = "no_entities"

            if not errors:
                # Detect removed entities and clean up their sequence rules
                old_entities = set(
                    self._config_entry.data.get(CONF_ENTITIES, [])
                )
                new_entities = set(entities)
                removed = old_entities - new_entities
                added = new_entities - old_entities
                if removed:
                    _LOGGER.info(
                        "Entities removed from config: %s. "
                        "Their profiles are preserved but excluded from "
                        "simulation; dependent SequenceRules will be "
                        "deactivated.",
                        ", ".join(sorted(removed)),
                    )
                if added:
                    _LOGGER.info(
                        "New entities added to config: %s. "
                        "Learning will begin on next coordinator cycle.",
                        ", ".join(sorted(added)),
                    )

                # Update entry.data directly so the coordinator and
                # simulation pick up the new configuration.  The
                # OptionsFlow normally writes to entry.options, but
                # the rest of the code reads from entry.data.
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=user_input
                )
                # Also write to options to trigger the reload listener.
                return self.async_create_entry(data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}
        schema = _build_data_schema(defaults=current)
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
