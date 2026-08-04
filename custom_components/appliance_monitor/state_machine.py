"""Appliance state machine — pure Python, no HA dependencies."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import islice
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Sequence

WH_PER_KWH = 1000.0


class ApplianceState(StrEnum):
    """Possible states of a monitored appliance."""

    IDLE = "idle"
    RUNNING = "running"
    POST_CYCLE = "post_cycle"
    FINISHED = "finished"
    DISCONNECTED = "disconnected"


# States in which the cycle is over and the load is ready to come out.
_LOAD_READY = frozenset({ApplianceState.POST_CYCLE, ApplianceState.FINISHED})


class _Sample(NamedTuple):
    """One recorded reading of the running energy total."""

    timestamp: datetime
    total_energy_kwh: float
    from_source: bool
    """False when the poll re-read a value the source never republished."""


@dataclass(frozen=True, slots=True)
class WindowMeasure:
    """One reading of a trailing window, as both checks and reports see it."""

    value: float | None
    """Wh consumed over the window — or watts when it degenerates to a point."""

    is_power: bool
    """True when the window is 0 and *value* is a live reading in watts."""

    source_sample_count: int
    """
    How many readings the source itself published inside the window.

    Poll re-reads are excluded: they carry no new information from the
    appliance, so counting them would hide a silent source behind a floor of
    roughly one sample per poll interval. Zero therefore honestly means the
    source said nothing at all during this window.
    """


class ApplianceStateMachine:
    """
    Tracks appliance state from power readings.

    Starting is decided on instantaneous power, so a cycle is picked up at
    once. Ending is decided on the energy consumed within a sliding window,
    which rides through the low-draw phases mid-cycle that instantaneous
    thresholds cannot tell apart from a finished cycle.
    """

    # Mirrors the config-entry options one-to-one; bundling them into a
    # dataclass would only move the argument list somewhere else.
    def __init__(  # noqa: PLR0913
        self,
        *,
        start_threshold: float,
        start_delay_seconds: float = 0,
        finished_window_seconds: float,
        finished_energy_threshold_wh: float,
        post_cycle_enabled: bool = False,
        post_cycle_window_seconds: float = 0,
        post_cycle_energy_threshold_wh: float = 0,
        observed_windows_seconds: Sequence[float] = (),
    ) -> None:
        """
        Initialise with threshold, window and energy threshold values.

        *observed_windows_seconds* take no part in detection; they only keep
        samples around long enough for something else to measure them.
        """
        self._start_threshold = start_threshold
        self._start_delay_seconds = start_delay_seconds
        self._finished_window_seconds = finished_window_seconds
        self._finished_energy_threshold_wh = finished_energy_threshold_wh
        self._post_cycle_enabled = post_cycle_enabled
        self._post_cycle_window_seconds = post_cycle_window_seconds
        self._post_cycle_energy_threshold_wh = post_cycle_energy_threshold_wh
        self._observed_windows_seconds = tuple(observed_windows_seconds)
        self._state: ApplianceState = ApplianceState.IDLE
        self._state_before_disconnect: ApplianceState = ApplianceState.IDLE
        self._above_threshold_since: datetime | None = None
        self._cycle_start: datetime | None = None
        self._cycle_duration_seconds: float = 0.0
        self._total_operating_seconds: float = 0.0
        self._cycle_energy_kwh: float = 0.0
        self._total_energy_kwh: float = 0.0
        self._last_update: datetime | None = None
        self._last_power: float = 0.0
        self._cycle_count: int = 0
        # (timestamp, total_energy_kwh) samples spanning the longest window.
        self._samples: deque[tuple[datetime, float]] = deque()

    @property
    def _longest_window_seconds(self) -> float:
        """Return the longest window any check or observer needs samples for."""
        windows = [self._finished_window_seconds, *self._observed_windows_seconds]
        if self._post_cycle_enabled:
            windows.append(self._post_cycle_window_seconds)
        return max(windows)

    def update(self, power: float, now: datetime, *, from_source: bool = False) -> None:
        """
        Advance the state machine with a new power reading.

        *from_source* marks a value the source itself published, as opposed to
        a poll re-reading one it had already reported. Detection treats both
        alike — a repeated value is still evidence of consumption — but only
        the former counts as the source having said something.
        """
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
            # The cycle keeps consuming while it idles after the programme, so
            # its energy runs on to FINISHED. Its duration does not: the work
            # stopped when RUNNING did.
            if self._state in {ApplianceState.RUNNING, ApplianceState.POST_CYCLE}:
                self._cycle_energy_kwh += energy_kwh
            if self._state is ApplianceState.RUNNING:
                self._total_operating_seconds += dt_seconds
                if self._cycle_start is not None:
                    self._cycle_duration_seconds = max(
                        0.0, (now - self._cycle_start).total_seconds()
                    )
        self._last_update = now
        self._last_power = power
        self._record_sample(now, from_source=from_source)

        if self._state is ApplianceState.IDLE:
            self._handle_idle(power, now)
        elif self._state is ApplianceState.RUNNING:
            self._handle_running()
        elif self._state is ApplianceState.POST_CYCLE:
            self._handle_post_cycle()
        elif self._state is ApplianceState.FINISHED:
            self._handle_finished(power, now)

    def _record_sample(self, now: datetime, *, from_source: bool = False) -> None:
        """Append the running energy total and drop samples past the window."""
        self._samples.append(_Sample(now, self._total_energy_kwh, from_source))
        cutoff = now - timedelta(seconds=self._longest_window_seconds)
        # Keep the newest sample at or before the cutoff — it is the left edge
        # of the window; everything older than that one is dead weight.
        while len(self._samples) > 1 and self._samples[1][0] <= cutoff:
            self._samples.popleft()

    def window_measure(self, window_seconds: float) -> WindowMeasure:
        """
        Measure the trailing window once, for both deciding and reporting.

        The windowed measure is the rise of the cumulative energy curve; over
        the window's length that is an average rate, and as the window shrinks
        the rate converges on the power at that instant. A window of 0 is
        therefore the same check taken at a point, with the value read in
        watts rather than Wh — exact for appliances that drop straight to zero,
        and as fast as the source reports.

        A `value` of None means "no verdict": the samples do not span the full
        window, as after a restart, a source outage, or early in a cycle. Every
        caller must treat that as "keep the current state".
        """
        if window_seconds <= 0:
            last = self._samples[-1] if self._samples else None
            return WindowMeasure(
                value=self._last_power,
                is_power=True,
                source_sample_count=1 if last is not None and last.from_source else 0,
            )
        if len(self._samples) < 2:  # noqa: PLR2004
            return WindowMeasure(
                None, is_power=False, source_sample_count=self._source_count_from(0)
            )
        now, total, _ = self._samples[-1]
        cutoff = now - timedelta(seconds=window_seconds)
        index: int | None = None
        for i, sample in enumerate(self._samples):
            if sample.timestamp > cutoff:
                break
            index = i
        if index is None:
            return WindowMeasure(
                None, is_power=False, source_sample_count=self._source_count_from(0)
            )
        # The sample at *index* sits on or before the window's edge, so only the
        # ones after it were published while the window was open.
        source_sample_count = self._source_count_from(index + 1)
        base_time, base, _ = self._samples[index]
        if index + 1 < len(self._samples):
            next_time, next_value, _ = self._samples[index + 1]
            span = (next_time - base_time).total_seconds()
            if span > 0:
                # The sample straddling the window edge only counts for the
                # share of its interval that falls inside, so the measure
                # covers exactly the window — including windows shorter than
                # the source's update interval.
                inside = (cutoff - base_time).total_seconds()
                base += (next_value - base) * (inside / span)
        return WindowMeasure(
            value=(total - base) * WH_PER_KWH,
            is_power=False,
            source_sample_count=source_sample_count,
        )

    def _source_count_from(self, start: int) -> int:
        """Count source-published readings from *start* onwards."""
        return sum(
            1 for sample in islice(self._samples, start, None) if sample.from_source
        )

    def window_energy_wh(self, window_seconds: float) -> float | None:
        """Return Wh over the trailing window, or None if there is no verdict."""
        measure = self.window_measure(window_seconds)
        return None if measure.is_power else measure.value

    def _is_below(self, window_seconds: float, threshold: float) -> bool | None:
        """Return whether the window is under *threshold*, or None for no verdict."""
        value = self.window_measure(window_seconds).value
        if value is None:
            return None
        return value < threshold

    def _try_start_running(self, now: datetime) -> None:
        """Transition to RUNNING if the start delay has elapsed."""
        if self._above_threshold_since is None:
            self._above_threshold_since = now
        elapsed = (now - self._above_threshold_since).total_seconds()
        if elapsed >= self._start_delay_seconds:
            self._begin_cycle(now)

    def _begin_cycle(self, now: datetime) -> None:
        """Enter RUNNING and start a fresh cycle."""
        self._state = ApplianceState.RUNNING
        self._cycle_start = now
        self._cycle_duration_seconds = 0.0
        self._cycle_energy_kwh = 0.0
        self._above_threshold_since = None
        # Samples from before the cycle would make it look idle at once. The
        # reading that started it is re-recorded as the window's first sample,
        # so it must keep the provenance it arrived with.
        from_source = bool(self._samples) and self._samples[-1].from_source
        self._samples.clear()
        self._record_sample(now, from_source=from_source)

    def _handle_idle(self, power: float, now: datetime) -> None:
        if power >= self._start_threshold:
            self._try_start_running(now)
        else:
            self._above_threshold_since = None

    def _handle_running(self) -> None:
        # With the post-cycle phase on, RUNNING only ever hands over to it;
        # FINISHED is then reached from there, never directly.
        if self._post_cycle_enabled:
            if self._is_below(
                self._post_cycle_window_seconds,
                self._post_cycle_energy_threshold_wh,
            ):
                self._end_cycle(ApplianceState.POST_CYCLE)
            return
        if self._is_below(
            self._finished_window_seconds,
            self._finished_energy_threshold_wh,
        ):
            self._end_cycle(ApplianceState.FINISHED)

    def _handle_post_cycle(self) -> None:
        # FINISHED is the only way out. A new cycle cannot start from here:
        # the draw while idling after a cycle can sit above start_threshold (a
        # washing machine holds 10-16 W), so any live-power check would restart
        # the cycle over and over. Starting a new load before the appliance
        # goes quiet therefore needs the unloaded button first, which is no
        # imposition — the appliance has to be emptied for that anyway.
        if self._is_below(
            self._finished_window_seconds,
            self._finished_energy_threshold_wh,
        ):
            self._state = ApplianceState.FINISHED

    _handle_finished = (
        _handle_idle  # FINISHED handles the start spike exactly like IDLE
    )

    def _end_cycle(self, state: ApplianceState) -> None:
        """Leave RUNNING for *state*, counting the cycle exactly once."""
        self._state = state
        self._cycle_count += 1
        self._above_threshold_since = None

    def reset(self) -> None:
        """
        Force the state machine back to IDLE.

        Cycle count and total operating time are preserved.
        """
        self._state = ApplianceState.IDLE
        self._state_before_disconnect = ApplianceState.IDLE
        self._above_threshold_since = None
        self._cycle_start = None
        self._cycle_duration_seconds = 0.0
        self._cycle_energy_kwh = 0.0
        self._last_update = None
        self._samples.clear()

    def mark_unloaded(self) -> None:
        """
        Acknowledge a finished cycle: POST_CYCLE or FINISHED to IDLE.

        The load is ready in both states. Unloading also ends the post-cycle
        phase, since emptying the appliance means it was opened — and it is
        the only way out of a phase no cycle can start from. A press made in
        error costs no more than the rest of that phase going unreported.

        A no-op in any other state. Last-cycle metrics are kept.
        """
        if self._state in _LOAD_READY:
            self._state = ApplianceState.IDLE
        elif (
            self._state is ApplianceState.DISCONNECTED
            and self._state_before_disconnect in _LOAD_READY
        ):
            # Reconnect resumes IDLE instead of the acknowledged state.
            self._state_before_disconnect = ApplianceState.IDLE

    def mark_disconnected(self) -> None:
        """
        Mark the source sensor as unavailable.

        Behaves like an HA restart: state and totals are preserved, but no
        energy is integrated and the sample window is dropped, so no check
        runs again until a fresh window has been collected.
        """
        if self._state is ApplianceState.DISCONNECTED:
            return
        self._state_before_disconnect = self._state
        self._state = ApplianceState.DISCONNECTED
        self._above_threshold_since = None
        self._last_update = None
        self._samples.clear()

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
        """Return True while the appliance is actively working."""
        return self._state is ApplianceState.RUNNING

    @property
    def is_post_cycle(self) -> bool:
        """Return True while the appliance idles after a completed cycle."""
        return self._state is ApplianceState.POST_CYCLE

    @property
    def is_finished(self) -> bool:
        """
        Return True once the cycle is done.

        Covers POST_CYCLE as well: the load is ready at that point, which is
        what an automation waiting on "finished" cares about.
        """
        return self._state in _LOAD_READY

    @property
    def cycle_start(self) -> datetime | None:
        """Return when the current or last cycle started, or None if never run."""
        return self._cycle_start

    @property
    def cycle_duration_seconds(self) -> float:
        """
        Return wall-clock cycle duration in seconds.

        Frozen when RUNNING ends, zero before first cycle and after reset.
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

        Keeps counting through the post-cycle phase and freezes on reaching
        FINISHED; zero before first cycle and after reset.
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
