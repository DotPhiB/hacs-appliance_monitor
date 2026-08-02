"""DataUpdateCoordinator for appliance_monitor."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import utcnow

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
    DOMAIN,
    LOGGER,
)
from .state_machine import ApplianceState, ApplianceStateMachine

STORAGE_VERSION = 1
PERSIST_DELAY_SECONDS = 10.0

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
            update_interval=timedelta(seconds=10),
        )
        self.config_entry = config_entry
        self._state_machine = ApplianceStateMachine(
            start_threshold=self._conf(CONF_START_THRESHOLD),
            start_delay_seconds=self._conf(CONF_START_DELAY, DEFAULT_START_DELAY),
            finished_window_seconds=self._conf(
                CONF_FINISHED_WINDOW, DEFAULT_FINISHED_WINDOW
            ),
            finished_energy_threshold_wh=self._conf(
                CONF_FINISHED_ENERGY_THRESHOLD, DEFAULT_FINISHED_ENERGY_THRESHOLD
            ),
            post_cycle_enabled=self._conf(
                CONF_POST_CYCLE_ENABLED, DEFAULT_POST_CYCLE_ENABLED
            ),
            post_cycle_window_seconds=self._conf(
                CONF_POST_CYCLE_WINDOW, DEFAULT_POST_CYCLE_WINDOW
            ),
            post_cycle_energy_threshold_wh=self._conf(
                CONF_POST_CYCLE_ENERGY_THRESHOLD, DEFAULT_POST_CYCLE_ENERGY_THRESHOLD
            ),
        )
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{config_entry.entry_id}",
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
            self._state_machine.mark_disconnected()
            self._schedule_persist()
            return self._current_data()

        try:
            power = float(state.state)
        except ValueError:
            LOGGER.warning(
                "Power sensor %s returned non-numeric value: %s",
                entity_id,
                state.state,
            )
            self._state_machine.mark_disconnected()
            self._schedule_persist()
            return self._current_data()

        cycle_count_before = self._state_machine.cycle_count
        self._state_machine.update(power, utcnow())
        if self._state_machine.cycle_count > cycle_count_before:
            # Cycle just finished — persist immediately so an ungraceful
            # shutdown before the debounce fires can't drop the count.
            await self._async_persist_now()
        else:
            self._schedule_persist()
        return self._current_data(power)

    async def async_load_persisted_snapshot(self) -> None:
        """Restore persisted state and totals into the state machine."""
        data = await self._store.async_load()
        if not data:
            return
        try:
            state = ApplianceState(data.get("state", ApplianceState.IDLE.value))
        except ValueError:
            state = ApplianceState.IDLE
        try:
            state_before_disconnect = ApplianceState(
                data.get(
                    "state_before_disconnect",
                    ApplianceState.IDLE.value,
                ),
            )
        except ValueError:
            state_before_disconnect = ApplianceState.IDLE
        cycle_start_raw = data.get("cycle_start")
        try:
            cycle_start = (
                datetime.fromisoformat(cycle_start_raw) if cycle_start_raw else None
            )
        except TypeError, ValueError:
            cycle_start = None
        self._state_machine.restore_snapshot(
            cycle_count=int(data.get("cycle_count", 0)),
            total_operating_seconds=float(data.get("total_operating_seconds", 0.0)),
            total_energy_kwh=float(data.get("total_energy_kwh", 0.0)),
            state=state,
            state_before_disconnect=state_before_disconnect,
            cycle_start=cycle_start,
            cycle_duration_seconds=float(data.get("cycle_duration_seconds", 0.0)),
            cycle_energy_kwh=float(data.get("cycle_energy_kwh", 0.0)),
        )

    def _schedule_persist(self) -> None:
        """Queue a debounced write of state and totals; HA also flushes on shutdown."""
        self._store.async_delay_save(self._snapshot_for_persist, PERSIST_DELAY_SECONDS)

    async def _async_persist_now(self) -> None:
        """Write the snapshot immediately, bypassing the debounce."""
        await self._store.async_save(self._snapshot_for_persist())

    def _snapshot_for_persist(self) -> dict[str, Any]:
        """Build the dict written to .storage at the next debounced save."""
        sm = self._state_machine
        return {
            "cycle_count": sm.cycle_count,
            "total_operating_seconds": sm.total_operating_seconds,
            "total_energy_kwh": sm.total_energy_kwh,
            "state": str(sm.state),
            "state_before_disconnect": str(sm.state_before_disconnect),
            "cycle_start": sm.cycle_start.isoformat() if sm.cycle_start else None,
            "cycle_duration_seconds": sm.cycle_duration_seconds,
            "cycle_energy_kwh": sm.cycle_energy_kwh,
        }

    def _current_data(self, power: float | None = None) -> dict[str, Any]:
        """Snapshot the state machine into a coordinator data dict."""
        if power is None:
            power = self.data.get("power", 0.0) if self.data else 0.0
        return {
            "state": str(self._state_machine.state),
            "running": self._state_machine.is_running,
            "finished": self._state_machine.is_finished,
            "post_cycle": self._state_machine.is_post_cycle,
            "cycle_start": self._state_machine.cycle_start,
            "cycle_duration": self._state_machine.cycle_duration_seconds,
            "cycle_energy": self._state_machine.cycle_energy_kwh,
            "total_operating_time": self._state_machine.total_operating_seconds,
            "total_energy": self._state_machine.total_energy_kwh,
            "cycle_count": self._state_machine.cycle_count,
            "power": power,
        }

    async def reset(self) -> None:
        """Reset the appliance state to IDLE; cycle count is preserved."""
        self._state_machine.reset()
        await self._async_persist_now()
        self.async_set_updated_data(self._current_data())

    async def unloaded(self) -> None:
        """Acknowledge a finished cycle: FINISHED to IDLE, metrics kept."""
        self._state_machine.mark_unloaded()
        await self._async_persist_now()
        self.async_set_updated_data(self._current_data())

    async def reset_cycle_count(self) -> None:
        """Zero the cycle counter without affecting the current state."""
        self._state_machine.reset_cycle_count()
        await self._async_persist_now()
        self.async_set_updated_data(self._current_data())
