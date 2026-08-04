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
    TRIGGER_COMMAND,
    TRIGGER_POLL,
    TRIGGER_SOURCE_UPDATE,
    TUNING_FINISHED,
    TUNING_FIXED_WINDOWS,
    TUNING_KEY_PREFIX,
    TUNING_POST_CYCLE,
)
from .state_machine import ApplianceState, ApplianceStateMachine

STORAGE_VERSION = 1
PERSIST_DELAY_SECONDS = 10.0
HEADROOM_PRECISION = 3


def _headroom_ratio(value: float | None, threshold: float) -> float | None:
    """
    Return how the window currently sits relative to its threshold.

    1.0 is the crossing point: above it the window is still over its threshold,
    below it the check fires. This is the number tuning is really about — how
    much room a threshold has before it stops separating the two phases — and
    it works for a zero-length window too, where both sides are watts.
    """
    if value is None or threshold <= 0:
        return None
    return round(value / threshold, HEADROOM_PRECISION)


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
            observed_windows_seconds=[width for _, width in TUNING_FIXED_WINDOWS],
        )
        # Set by the source-change listener; every other refresh is the poll.
        self._pending_trigger = TRIGGER_POLL
        self._trigger = TRIGGER_POLL
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

    async def async_source_changed(self) -> None:
        """Refresh because the source sensor published a new value."""
        self._pending_trigger = TRIGGER_SOURCE_UPDATE
        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        """Read the power sensor state and advance the state machine."""
        self._trigger = self._pending_trigger
        self._pending_trigger = TRIGGER_POLL
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
        self._state_machine.update(
            power,
            utcnow(),
            from_source=self._trigger == TRIGGER_SOURCE_UPDATE,
        )
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

    def _tuning_windows(self) -> tuple[tuple[str, float, float | None], ...]:
        """Return (key suffix, window seconds, threshold) for every tuning sensor."""
        return (
            *((name, float(width), None) for name, width in TUNING_FIXED_WINDOWS),
            (
                TUNING_FINISHED,
                float(self._conf(CONF_FINISHED_WINDOW, DEFAULT_FINISHED_WINDOW)),
                float(
                    self._conf(
                        CONF_FINISHED_ENERGY_THRESHOLD,
                        DEFAULT_FINISHED_ENERGY_THRESHOLD,
                    )
                ),
            ),
            (
                TUNING_POST_CYCLE,
                float(self._conf(CONF_POST_CYCLE_WINDOW, DEFAULT_POST_CYCLE_WINDOW)),
                float(
                    self._conf(
                        CONF_POST_CYCLE_ENERGY_THRESHOLD,
                        DEFAULT_POST_CYCLE_ENERGY_THRESHOLD,
                    )
                ),
            ),
        )

    def _tuning_data(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        """Measure every tuning window and describe how it was measured."""
        values: dict[str, Any] = {}
        attributes: dict[str, dict[str, Any]] = {}
        for name, window, threshold in self._tuning_windows():
            key = f"{TUNING_KEY_PREFIX}{name}"
            measure = self._state_machine.window_measure(window)
            # A zero-length window is judged on live power, not on an energy
            # budget, so there is no Wh figure to plot — the source's own power
            # graph is the tuning view in that case.
            values[key] = None if measure.is_power else measure.value
            attrs: dict[str, Any] = {
                "window_seconds": window,
                "source_samples_in_window": measure.source_sample_count,
                "trigger": self._trigger,
                "measures": "power" if measure.is_power else "energy",
            }
            if threshold is not None:
                attrs["threshold"] = threshold
                attrs["threshold_unit"] = "W" if measure.is_power else "Wh"
                attrs["headroom_ratio"] = _headroom_ratio(measure.value, threshold)
            attributes[key] = attrs
        return values, attributes

    def _current_data(self, power: float | None = None) -> dict[str, Any]:
        """Snapshot the state machine into a coordinator data dict."""
        if power is None:
            power = self.data.get("power", 0.0) if self.data else 0.0
        tuning_values, tuning_attributes = self._tuning_data()
        return {
            **tuning_values,
            "attributes": tuning_attributes,
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
        self._trigger = TRIGGER_COMMAND
        self.async_set_updated_data(self._current_data())

    async def unloaded(self) -> None:
        """Acknowledge a finished cycle: POST_CYCLE/FINISHED to IDLE, metrics kept."""
        self._state_machine.mark_unloaded()
        await self._async_persist_now()
        self._trigger = TRIGGER_COMMAND
        self.async_set_updated_data(self._current_data())

    async def reset_cycle_count(self) -> None:
        """Zero the cycle counter without affecting the current state."""
        self._state_machine.reset_cycle_count()
        await self._async_persist_now()
        self._trigger = TRIGGER_COMMAND
        self.async_set_updated_data(self._current_data())
