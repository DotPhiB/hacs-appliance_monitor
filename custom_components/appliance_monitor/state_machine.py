"""Appliance state machine — pure Python, no HA dependencies."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class ApplianceState(StrEnum):
    """Possible states of a monitored appliance."""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    DISCONNECTED = "disconnected"


class ApplianceStateMachine:
    """Tracks appliance state based on power readings."""

    def __init__(
        self,
        start_threshold: float,
        idle_threshold: float,
        idle_timeout_seconds: float,
        start_delay_seconds: float = 0,
    ) -> None:
        """Initialise with threshold and timeout values."""
        self._start_threshold = start_threshold
        self._idle_threshold = idle_threshold
        self._idle_timeout_seconds = idle_timeout_seconds
        self._start_delay_seconds = start_delay_seconds
        self._state: ApplianceState = ApplianceState.IDLE
        self._state_before_disconnect: ApplianceState = ApplianceState.IDLE
        self._above_threshold_since: datetime | None = None
        self._below_idle_since: datetime | None = None
        self._cycle_start: datetime | None = None
        self._cycle_duration_seconds: float = 0.0
        self._total_operating_seconds: float = 0.0
        self._cycle_energy_kwh: float = 0.0
        self._total_energy_kwh: float = 0.0
        self._last_update: datetime | None = None
        self._last_power: float = 0.0
        self._cycle_count: int = 0

    def update(self, power: float, now: datetime) -> None:
        """Advance the state machine with a new power reading."""
        if self._state is ApplianceState.DISCONNECTED:
            self._state = self._state_before_disconnect
            self._state_before_disconnect = ApplianceState.IDLE
        if self._last_update is not None:
            dt_seconds = (now - self._last_update).total_seconds()
            # Clock jumped backward (e.g. NTP correction on a clock-less RPi);
            # skip integration this tick to avoid negative energy/operating time.
            if dt_seconds < 0:
                dt_seconds = 0.0
            avg_power_w = (self._last_power + power) / 2.0
            energy_kwh = avg_power_w * dt_seconds / 3_600_000.0
            self._total_energy_kwh += energy_kwh
            if self._state is ApplianceState.RUNNING:
                self._total_operating_seconds += dt_seconds
                self._cycle_energy_kwh += energy_kwh
                if self._cycle_start is not None:
                    self._cycle_duration_seconds = max(
                        0.0, (now - self._cycle_start).total_seconds()
                    )
        self._last_update = now
        self._last_power = power

        if self._state is ApplianceState.IDLE:
            self._handle_idle(power, now)
        elif self._state is ApplianceState.RUNNING:
            self._handle_running(power, now)
        elif self._state is ApplianceState.FINISHED:
            self._handle_finished(power, now)

    def _try_start_running(self, now: datetime) -> None:
        """Transition to RUNNING if the start delay has elapsed."""
        if self._above_threshold_since is None:
            self._above_threshold_since = now
        elapsed = (now - self._above_threshold_since).total_seconds()
        if elapsed >= self._start_delay_seconds:
            self._state = ApplianceState.RUNNING
            self._cycle_start = now
            self._cycle_duration_seconds = 0.0
            self._cycle_energy_kwh = 0.0
            self._below_idle_since = None
            self._above_threshold_since = None

    def _handle_idle(self, power: float, now: datetime) -> None:
        if power >= self._start_threshold:
            self._try_start_running(now)
        else:
            self._above_threshold_since = None

    def _handle_running(self, power: float, now: datetime) -> None:
        if power < self._idle_threshold:
            if self._below_idle_since is None:
                self._below_idle_since = now
            elapsed = (now - self._below_idle_since).total_seconds()
            if elapsed >= self._idle_timeout_seconds:
                self._state = ApplianceState.FINISHED
                self._cycle_count += 1
                self._below_idle_since = None
        else:
            self._below_idle_since = None

    _handle_finished = (
        _handle_idle  # FINISHED handles the start spike exactly like IDLE
    )

    def reset(self) -> None:
        """
        Force the state machine back to IDLE.

        Cycle count and total operating time are preserved.
        """
        self._state = ApplianceState.IDLE
        self._state_before_disconnect = ApplianceState.IDLE
        self._above_threshold_since = None
        self._below_idle_since = None
        self._cycle_start = None
        self._cycle_duration_seconds = 0.0
        self._cycle_energy_kwh = 0.0
        self._last_update = None

    def mark_unloaded(self) -> None:
        """
        Acknowledge a finished cycle: FINISHED to IDLE.

        A no-op in any other state. Last-cycle metrics are kept.
        """
        if self._state is ApplianceState.FINISHED:
            self._state = ApplianceState.IDLE
        elif (
            self._state is ApplianceState.DISCONNECTED
            and self._state_before_disconnect is ApplianceState.FINISHED
        ):
            # Reconnect resumes IDLE instead of FINISHED.
            self._state_before_disconnect = ApplianceState.IDLE

    def mark_disconnected(self) -> None:
        """
        Mark the source sensor as unavailable.

        Behaves like an HA restart: state and totals are preserved, but no
        energy is integrated and no hysteresis timers advance until a fresh
        sample arrives.
        """
        if self._state is ApplianceState.DISCONNECTED:
            return
        self._state_before_disconnect = self._state
        self._state = ApplianceState.DISCONNECTED
        self._above_threshold_since = None
        self._below_idle_since = None
        self._last_update = None

    def reset_cycle_count(self) -> None:
        """Zero the cycle counter without affecting state or operating time."""
        self._cycle_count = 0

    # too-many-arguments (PLR0913) is fine here: this mirrors persisted snapshot
    # fields one-to-one; bundling into a dataclass would add ceremony without payoff.
    def restore_snapshot(  # noqa: PLR0913
        self,
        *,
        cycle_count: int = 0,
        total_operating_seconds: float = 0.0,
        total_energy_kwh: float = 0.0,
        state: ApplianceState = ApplianceState.IDLE,
        state_before_disconnect: ApplianceState = ApplianceState.IDLE,
        cycle_start: datetime | None = None,
        cycle_duration_seconds: float = 0.0,
        cycle_energy_kwh: float = 0.0,
    ) -> None:
        """Restore state machine fields from persisted storage."""
        self._cycle_count = cycle_count
        self._total_operating_seconds = total_operating_seconds
        self._total_energy_kwh = total_energy_kwh
        self._state = state
        self._state_before_disconnect = state_before_disconnect
        self._cycle_start = cycle_start
        self._cycle_duration_seconds = cycle_duration_seconds
        self._cycle_energy_kwh = cycle_energy_kwh

    @property
    def state(self) -> ApplianceState:
        """Return current state."""
        return self._state

    @property
    def state_before_disconnect(self) -> ApplianceState:
        """Return the state to resume to when the source reconnects."""
        return self._state_before_disconnect

    @property
    def is_running(self) -> bool:
        """Return True while the appliance is running."""
        return self._state is ApplianceState.RUNNING

    @property
    def is_finished(self) -> bool:
        """Return True when a cycle just finished."""
        return self._state is ApplianceState.FINISHED

    @property
    def cycle_start(self) -> datetime | None:
        """Return when the current or last cycle started, or None if never run."""
        return self._cycle_start

    @property
    def cycle_duration_seconds(self) -> float:
        """
        Return wall-clock cycle duration in seconds.

        Frozen at FINISHED, zero before first cycle and after reset.
        """
        return self._cycle_duration_seconds

    @property
    def total_operating_seconds(self) -> float:
        """Return lifetime seconds spent in RUNNING; never reset."""
        return self._total_operating_seconds

    @property
    def cycle_energy_kwh(self) -> float:
        """
        Return energy consumed during the current or last cycle in kWh.

        Frozen at FINISHED, zero before first cycle and after reset.
        """
        return self._cycle_energy_kwh

    @property
    def total_energy_kwh(self) -> float:
        """Return lifetime energy in kWh integrated from every reading; never reset."""
        return self._total_energy_kwh

    @property
    def cycle_count(self) -> int:
        """Return the number of completed cycles since last counter reset."""
        return self._cycle_count
