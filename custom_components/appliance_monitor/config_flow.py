"""Config flow for Appliance Monitor."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_IDLE_THRESHOLD,
    CONF_IDLE_TIMEOUT,
    CONF_POWER_SENSOR,
    CONF_START_THRESHOLD,
    DEFAULT_IDLE_THRESHOLD,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_START_THRESHOLD,
    DOMAIN,
)


class ApplianceMonitorFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Appliance Monitor."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entity_id: str = user_input[CONF_POWER_SENSOR]
            state = self.hass.states.get(entity_id)
            if state is None:
                errors[CONF_POWER_SENSOR] = "sensor_not_found"
            else:
                try:
                    float(state.state)
                except ValueError:
                    errors[CONF_POWER_SENSOR] = "sensor_not_numeric"

            if not errors:
                await self.async_set_unique_id(entity_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=entity_id,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POWER_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor"),
                    ),
                    vol.Required(
                        CONF_START_THRESHOLD,
                        default=(user_input or {}).get(
                            CONF_START_THRESHOLD, DEFAULT_START_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=10000,
                            step=0.5,
                            unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                    vol.Required(
                        CONF_IDLE_THRESHOLD,
                        default=(user_input or {}).get(
                            CONF_IDLE_THRESHOLD, DEFAULT_IDLE_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=10000,
                            step=0.5,
                            unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                    vol.Required(
                        CONF_IDLE_TIMEOUT,
                        default=(user_input or {}).get(
                            CONF_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=60,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                }
            ),
            errors=errors,
        )
