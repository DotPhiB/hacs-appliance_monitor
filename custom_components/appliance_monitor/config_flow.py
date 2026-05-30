"""Config flow for Appliance Monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS
from homeassistant.helpers import selector

from .const import (
    CONF_IDLE_THRESHOLD,
    CONF_IDLE_TIMEOUT,
    CONF_PAUSE_DELAY,
    CONF_POWER_SENSOR,
    CONF_START_DELAY,
    CONF_START_THRESHOLD,
    DEFAULT_IDLE_THRESHOLD,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_PAUSE_DELAY,
    DEFAULT_START_DELAY,
    DEFAULT_START_THRESHOLD,
    DOMAIN,
)

if TYPE_CHECKING:
    from .data import ApplianceMonitorConfigEntry


def _threshold_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the vol.Schema for tunable threshold fields."""
    return vol.Schema(
        {
            vol.Required(
                CONF_START_THRESHOLD,
                default=defaults.get(CONF_START_THRESHOLD, DEFAULT_START_THRESHOLD),
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
                CONF_START_DELAY,
                default=defaults.get(CONF_START_DELAY, DEFAULT_START_DELAY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=600,
                    step=5,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Required(
                CONF_IDLE_THRESHOLD,
                default=defaults.get(CONF_IDLE_THRESHOLD, DEFAULT_IDLE_THRESHOLD),
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
                CONF_PAUSE_DELAY,
                default=defaults.get(CONF_PAUSE_DELAY, DEFAULT_PAUSE_DELAY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=600,
                    step=5,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Required(
                CONF_IDLE_TIMEOUT,
                default=defaults.get(CONF_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT),
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
    )


class ApplianceMonitorFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Appliance Monitor."""

    VERSION = 1

    _pending_input: dict[str, Any] | None = None
    _pending_device_class: str | None = None

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
                device_class = state.attributes.get(ATTR_DEVICE_CLASS)
                if device_class != SensorDeviceClass.POWER:
                    self._pending_input = user_input
                    self._pending_device_class = device_class
                    return await self.async_step_confirm_non_power()

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
                }
            ).extend(_threshold_schema(user_input or {}).schema),
            errors=errors,
        )

    async def async_step_confirm_non_power(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm using a sensor whose device_class is not 'power'."""
        if user_input is not None and self._pending_input is not None:
            entity_id: str = self._pending_input[CONF_POWER_SENSOR]
            await self.async_set_unique_id(entity_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=entity_id,
                data=self._pending_input,
            )

        entity_id = (
            self._pending_input[CONF_POWER_SENSOR] if self._pending_input else ""
        )
        return self.async_show_form(
            step_id="confirm_non_power",
            data_schema=vol.Schema({}),
            description_placeholders={
                "entity_id": entity_id,
                "device_class": self._pending_device_class or "unknown",
            },
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: ApplianceMonitorConfigEntry,
    ) -> ApplianceMonitorOptionsFlowHandler:
        """Return the options flow handler."""
        return ApplianceMonitorOptionsFlowHandler(config_entry)


class ApplianceMonitorOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for Appliance Monitor — lets users retune thresholds post-setup."""

    def __init__(self, config_entry: ApplianceMonitorConfigEntry) -> None:
        """Store the config entry so we can read current values as defaults."""
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the options form and save on submit."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=_threshold_schema(current),
        )
