"""Config flow for Appliance Monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS
from homeassistant.helpers import selector

from .const import (
    CONF_FINISHED_ENERGY_THRESHOLD,
    CONF_FINISHED_WINDOW,
    CONF_POST_CYCLE_ENABLED,
    CONF_POST_CYCLE_ENERGY_THRESHOLD,
    CONF_POST_CYCLE_WINDOW,
    CONF_POWER_SENSOR,
    CONF_START_DELAY,
    CONF_START_THRESHOLD,
    DEFAULT_FINISHED_ENERGY_THRESHOLD,
    DEFAULT_FINISHED_WINDOW,
    DEFAULT_POST_CYCLE_ENABLED,
    DEFAULT_POST_CYCLE_ENERGY_THRESHOLD,
    DEFAULT_POST_CYCLE_WINDOW,
    DEFAULT_START_DELAY,
    DEFAULT_START_THRESHOLD,
    DOMAIN,
)

if TYPE_CHECKING:
    from .data import ApplianceMonitorConfigEntry


def _window_selector() -> selector.NumberSelector:
    """Build the selector for a sliding-window length."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=10,
            max=3600,
            step=10,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX,
        ),
    )


def _energy_selector() -> selector.NumberSelector:
    """Build the selector for an energy budget within a window."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=1000,
            step=0.1,
            unit_of_measurement="Wh",
            mode=selector.NumberSelectorMode.BOX,
        ),
    )


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
                    step=1,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Required(
                CONF_FINISHED_WINDOW,
                default=defaults.get(CONF_FINISHED_WINDOW, DEFAULT_FINISHED_WINDOW),
            ): _window_selector(),
            vol.Required(
                CONF_FINISHED_ENERGY_THRESHOLD,
                default=defaults.get(
                    CONF_FINISHED_ENERGY_THRESHOLD, DEFAULT_FINISHED_ENERGY_THRESHOLD
                ),
            ): _energy_selector(),
            vol.Required(
                CONF_POST_CYCLE_ENABLED,
                default=defaults.get(
                    CONF_POST_CYCLE_ENABLED, DEFAULT_POST_CYCLE_ENABLED
                ),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_POST_CYCLE_WINDOW,
                default=defaults.get(CONF_POST_CYCLE_WINDOW, DEFAULT_POST_CYCLE_WINDOW),
            ): _window_selector(),
            vol.Required(
                CONF_POST_CYCLE_ENERGY_THRESHOLD,
                default=defaults.get(
                    CONF_POST_CYCLE_ENERGY_THRESHOLD, DEFAULT_POST_CYCLE_ENERGY_THRESHOLD
                ),
            ): _energy_selector(),
        }
    )


class ApplianceMonitorFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Appliance Monitor."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize per-flow state."""
        super().__init__()
        self._pending_input: dict[str, Any] | None = None
        self._pending_device_class: str | None = None

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
