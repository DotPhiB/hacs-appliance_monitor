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
    ) -> None:
        """Initialise with threshold and timeout values."""
        self._start_threshold = start_threshold
        self._idle_threshold = idle_threshold
        self._idle_timeout_seconds = idle_timeout_seconds
        self._state: ApplianceState = ApplianceState.IDLE
        self._pause_start: datetime | None = None
        self._runtime_seconds: float = 0.0
        self._last_update: datetime | None = None

    def update(self, power: float, now: datetime) -> None:
        """Advance the state machine with a new power reading."""
        if self._last_update is not None and self._state is ApplianceState.RUNNING:
            self._runtime_seconds += (now - self._last_update).total_seconds()
        self._last_update = now

        if self._state is ApplianceState.IDLE:
            if power > self._start_threshold:
                self._state = ApplianceState.RUNNING
                self._runtime_seconds = 0.0

        elif self._state is ApplianceState.RUNNING:
            if power < self._idle_threshold:
                self._state = ApplianceState.PAUSED
                self._pause_start = now

        elif self._state is ApplianceState.PAUSED:
            if power > self._start_threshold:
                self._state = ApplianceState.RUNNING
                self._pause_start = None
            elif (
                self._pause_start is not None
                and (now - self._pause_start).total_seconds()
                > self._idle_timeout_seconds
            ):
                self._state = ApplianceState.FINISHED

        elif self._state is ApplianceState.FINISHED and power > self._start_threshold:
            self._state = ApplianceState.RUNNING
            self._runtime_seconds = 0.0
            self._pause_start = None

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
