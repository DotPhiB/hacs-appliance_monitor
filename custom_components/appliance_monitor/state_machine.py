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
    PAUSED = "paused"
    FINISHED = "finished"


class ApplianceStateMachine:
    """Tracks appliance state based on power readings."""

    def __init__(
        self,
        start_threshold: float,
        idle_threshold: float,
        idle_timeout_seconds: float,
        start_delay_seconds: float = 0,
        pause_delay_seconds: float = 0,
    ) -> None:
        """Initialise with threshold and timeout values."""
        self._start_threshold = start_threshold
        self._idle_threshold = idle_threshold
        self._idle_timeout_seconds = idle_timeout_seconds
        self._start_delay_seconds = start_delay_seconds
        self._pause_delay_seconds = pause_delay_seconds
        self._state: ApplianceState = ApplianceState.IDLE
        self._pause_start: datetime | None = None
        self._above_threshold_since: datetime | None = None
        self._below_idle_since: datetime | None = None
        self._runtime_seconds: float = 0.0
        self._last_update: datetime | None = None

    def update(self, power: float, now: datetime) -> None:
        """Advance the state machine with a new power reading."""
        if self._last_update is not None and self._state is ApplianceState.RUNNING:
            self._runtime_seconds += (now - self._last_update).total_seconds()
        self._last_update = now

        if self._state is ApplianceState.IDLE:
            self._handle_idle(power, now)
        elif self._state is ApplianceState.RUNNING:
            self._handle_running(power, now)
        elif self._state is ApplianceState.PAUSED:
            self._handle_paused(power, now)
        elif self._state is ApplianceState.FINISHED:
            self._handle_finished(power, now)

    def _try_start_running(self, now: datetime) -> None:
        """Transition to RUNNING if the start delay has elapsed."""
        if self._above_threshold_since is None:
            self._above_threshold_since = now
        elapsed = (now - self._above_threshold_since).total_seconds()
        if elapsed >= self._start_delay_seconds:
            self._state = ApplianceState.RUNNING
            self._runtime_seconds = 0.0
            self._pause_start = None
            self._above_threshold_since = None

    def _handle_idle(self, power: float, now: datetime) -> None:
        if power > self._start_threshold:
            self._try_start_running(now)
        else:
            self._above_threshold_since = None

    def _handle_running(self, power: float, now: datetime) -> None:
        if power < self._idle_threshold:
            if self._below_idle_since is None:
                self._below_idle_since = now
            elapsed = (now - self._below_idle_since).total_seconds()
            if elapsed >= self._pause_delay_seconds:
                self._state = ApplianceState.PAUSED
                self._pause_start = now
                self._below_idle_since = None
        else:
            self._below_idle_since = None

    def _handle_paused(self, power: float, now: datetime) -> None:
        if power > self._start_threshold:
            self._state = ApplianceState.RUNNING
            self._pause_start = None
        elif (
            self._pause_start is not None
            and (now - self._pause_start).total_seconds() > self._idle_timeout_seconds
        ):
            self._state = ApplianceState.FINISHED

    def _handle_finished(self, power: float, now: datetime) -> None:
        if power > self._start_threshold:
            self._try_start_running(now)
        else:
            self._above_threshold_since = None

    def reset(self) -> None:
        """Force the state machine back to IDLE, clearing all in-progress timers."""
        self._state = ApplianceState.IDLE
        self._pause_start = None
        self._above_threshold_since = None
        self._below_idle_since = None
        self._runtime_seconds = 0.0
        self._last_update = None

    @property
    def state(self) -> ApplianceState:
        """Return current state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Return True while the appliance is running."""
        return self._state is ApplianceState.RUNNING

    @property
    def is_finished(self) -> bool:
        """Return True when a cycle just finished."""
        return self._state is ApplianceState.FINISHED

    @property
    def runtime_seconds(self) -> float:
        """Return accumulated runtime in seconds for the current cycle."""
        return self._runtime_seconds
