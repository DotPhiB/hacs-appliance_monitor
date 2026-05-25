"""DataUpdateCoordinator for appliance_monitor."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .const import (
    CONF_IDLE_THRESHOLD,
    CONF_IDLE_TIMEOUT,
    CONF_PAUSE_DELAY,
    CONF_POWER_SENSOR,
    CONF_START_DELAY,
    CONF_START_THRESHOLD,
    DEFAULT_PAUSE_DELAY,
    DEFAULT_START_DELAY,
    LOGGER,
)
from .state_machine import ApplianceStateMachine

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import ApplianceMonitorConfigEntry


class ApplianceMonitorCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the configured power sensor and drives the appliance state machine."""

    config_entry: ApplianceMonitorConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ApplianceMonitorConfigEntry,
    ) -> None:
        """Initialize coordinator and state machine from config entry data."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            name=f"appliance_monitor_{config_entry.entry_id}",
            update_interval=timedelta(seconds=30),
        )
        self.config_entry = config_entry
        self._state_machine = ApplianceStateMachine(
            start_threshold=self._conf(CONF_START_THRESHOLD),
            idle_threshold=self._conf(CONF_IDLE_THRESHOLD),
            idle_timeout_seconds=self._conf(CONF_IDLE_TIMEOUT) * 60,
            start_delay_seconds=self._conf(CONF_START_DELAY, DEFAULT_START_DELAY),
            pause_delay_seconds=self._conf(CONF_PAUSE_DELAY, DEFAULT_PAUSE_DELAY),
        )

    def _conf(self, key: str, default: Any = None) -> Any:
        """Return a config value from options, falling back to data then default."""
        return self.config_entry.options.get(
            key,
            self.config_entry.data.get(key, default),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Read the power sensor state and advance the state machine."""
        entity_id: str = self.config_entry.data[CONF_POWER_SENSOR]
        state = self.hass.states.get(entity_id)

        if state is None or state.state in {"unavailable", "unknown"}:
            msg = f"Power sensor {entity_id} is unavailable"
            raise UpdateFailed(msg)

        try:
            power = float(state.state)
        except ValueError as err:
            msg = f"Power sensor {entity_id} returned non-numeric value: {state.state}"
            raise UpdateFailed(msg) from err

        self._state_machine.update(power, utcnow())

        return {
            "state": str(self._state_machine.state),
            "running": self._state_machine.is_running,
            "finished": self._state_machine.is_finished,
            "runtime": self._state_machine.runtime_seconds,
            "power": power,
        }
