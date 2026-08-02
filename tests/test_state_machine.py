"""Tests for the ApplianceStateMachine."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.appliance_monitor.state_machine import (
    ApplianceState,
    ApplianceStateMachine,
)

START_THRESHOLD: float = 10.0
FINISHED_WINDOW: float = 300.0
FINISHED_ENERGY_WH: float = 0.3  # ≈ 3.6 W held over the window
POST_CYCLE_WINDOW: float = 300.0
POST_CYCLE_ENERGY_WH: float = 2.7  # ≈ 32 W held over the window

# Power levels, chosen relative to the budgets above.
WORKING: float = 100.0  # busts both budgets
POST_CYCLE: float = 20.0  # under the post-cycle budget, over the finished one
QUIET: float = 1.0  # under both
ABOVE_START: float = START_THRESHOLD + 1.0

T0 = datetime(2024, 1, 1)  # noqa: DTZ001


def _t(seconds: float) -> datetime:
    """Return T0 offset by *seconds*."""
    return T0 + timedelta(seconds=seconds)


def _feed(
    sm: ApplianceStateMachine,
    power: float,
    start: float,
    seconds: float,
    step: float = 10.0,
) -> float:
    """Feed constant *power* from *start* for *seconds*; return the end offset."""
    elapsed = 0.0
    while elapsed <= seconds:
        sm.update(power, _t(start + elapsed))
        elapsed += step
    return start + seconds


def _run_cycle(sm: ApplianceStateMachine, start: float = 0.0) -> float:
    """Drive sm from IDLE through a working phase; return the end offset."""
    sm.update(ABOVE_START, _t(start))
    return _feed(sm, WORKING, start, FINISHED_WINDOW)


@pytest.fixture
def sm() -> ApplianceStateMachine:
    """Return a fresh state machine with the post-cycle phase disabled."""
    return ApplianceStateMachine(
        start_threshold=START_THRESHOLD,
        finished_window_seconds=FINISHED_WINDOW,
        finished_energy_threshold_wh=FINISHED_ENERGY_WH,
    )


@pytest.fixture
def post_sm() -> ApplianceStateMachine:
    """Return a state machine with the post-cycle phase enabled."""
    return ApplianceStateMachine(
        start_threshold=START_THRESHOLD,
        finished_window_seconds=FINISHED_WINDOW,
        finished_energy_threshold_wh=FINISHED_ENERGY_WH,
        post_cycle_enabled=True,
        post_cycle_window_seconds=POST_CYCLE_WINDOW,
        post_cycle_energy_threshold_wh=POST_CYCLE_ENERGY_WH,
    )


class TestInitialState:
    """State machine starts correctly before any update."""

    def test_initial_state_is_idle(self, sm: ApplianceStateMachine) -> None:
        """State is IDLE on construction."""
        assert sm.state is ApplianceState.IDLE

    def test_initial_is_running_false(self, sm: ApplianceStateMachine) -> None:
        """is_running is False before any update."""
        assert not sm.is_running

    def test_initial_is_finished_false(self, sm: ApplianceStateMachine) -> None:
        """is_finished is False before any update."""
        assert not sm.is_finished

    def test_initial_cycle_duration_zero(self, sm: ApplianceStateMachine) -> None:
        """cycle_duration_seconds is zero before any update."""
        assert sm.cycle_duration_seconds == 0.0

    def test_initial_cycle_start_none(self, sm: ApplianceStateMachine) -> None:
        """cycle_start is None before any cycle has begun."""
        assert sm.cycle_start is None

    def test_initial_total_operating_zero(self, sm: ApplianceStateMachine) -> None:
        """total_operating_seconds is zero on construction."""
        assert sm.total_operating_seconds == 0.0

    def test_initial_cycle_count_zero(self, sm: ApplianceStateMachine) -> None:
        """cycle_count is zero on construction."""
        assert sm.cycle_count == 0


class TestIdleTransitions:
    """Transitions out of IDLE — decided on the live reading."""

    def test_transitions_to_running_at_threshold(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Power exactly at start_threshold triggers IDLE→RUNNING (inclusive)."""
        sm.update(START_THRESHOLD, _t(0))
        assert sm.state is ApplianceState.RUNNING

    def test_stays_idle_below_threshold(self, sm: ApplianceStateMachine) -> None:
        """Power below start_threshold keeps state IDLE."""
        sm.update(QUIET, _t(0))
        assert sm.state is ApplianceState.IDLE

    def test_cycle_duration_zero_on_start(self, sm: ApplianceStateMachine) -> None:
        """cycle_duration_seconds is zero on IDLE→RUNNING transition."""
        sm.update(ABOVE_START, _t(30))
        assert sm.cycle_duration_seconds == 0.0

    def test_cycle_start_set_on_running(self, sm: ApplianceStateMachine) -> None:
        """cycle_start is set to the transition timestamp on IDLE→RUNNING."""
        sm.update(ABOVE_START, _t(30))
        assert sm.cycle_start == _t(30)

    def test_idle_history_does_not_finish_new_cycle(
        self, sm: ApplianceStateMachine
    ) -> None:
        """A long quiet spell before the start cannot finish the cycle instantly."""
        _feed(sm, QUIET, 0, FINISHED_WINDOW * 2)
        sm.update(ABOVE_START, _t(FINISHED_WINDOW * 2 + 10))
        sm.update(QUIET, _t(FINISHED_WINDOW * 2 + 20))
        assert sm.state is ApplianceState.RUNNING


class TestRunningTransitions:
    """RUNNING ends on the energy consumed within the sliding window."""

    def test_no_verdict_before_window_is_full(self, sm: ApplianceStateMachine) -> None:
        """A cycle shorter than the window can never be declared finished."""
        sm.update(ABOVE_START, _t(0))
        _feed(sm, QUIET, 10, FINISHED_WINDOW - 60)
        assert sm.state is ApplianceState.RUNNING

    def test_finishes_after_a_quiet_window(self, sm: ApplianceStateMachine) -> None:
        """A full window under the energy budget ends the cycle."""
        sm.update(ABOVE_START, _t(0))
        _feed(sm, QUIET, 10, FINISHED_WINDOW)
        assert sm.state is ApplianceState.FINISHED

    def test_stays_running_while_working(self, sm: ApplianceStateMachine) -> None:
        """Sustained working draw keeps the cycle open."""
        _run_cycle(sm)
        assert sm.state is ApplianceState.RUNNING

    def test_low_draw_phase_shorter_than_window_keeps_running(
        self, sm: ApplianceStateMachine
    ) -> None:
        """A mid-cycle soak phase does not end the cycle."""
        end = _run_cycle(sm)
        end = _feed(sm, QUIET, end, FINISHED_WINDOW - 60)
        _feed(sm, WORKING, end, 60)
        assert sm.state is ApplianceState.RUNNING

    def test_brief_spike_does_not_delay_finish(self, sm: ApplianceStateMachine) -> None:
        """One blip inside an otherwise quiet window still finishes the cycle.

        This is the behaviour an idle timeout could not offer: a single sample
        above the threshold re-armed it and pushed the finish out indefinitely.
        """
        end = _run_cycle(sm)
        end = _feed(sm, QUIET, end, FINISHED_WINDOW / 2)
        sm.update(50.0, _t(end + 10))  # blip worth ≈0.14 Wh
        _feed(sm, QUIET, end + 20, FINISHED_WINDOW / 2)
        assert sm.state is ApplianceState.FINISHED

    def test_sustained_draw_inside_window_prevents_finish(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Draw that busts the budget keeps the cycle open even if it is low."""
        end = _run_cycle(sm)
        _feed(sm, POST_CYCLE, end, FINISHED_WINDOW * 2)
        assert sm.state is ApplianceState.RUNNING

    def test_cycle_duration_accumulates(self, sm: ApplianceStateMachine) -> None:
        """cycle_duration_seconds grows by elapsed seconds while RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        assert sm.cycle_duration_seconds == pytest.approx(30.0)

    def test_cycle_duration_frozen_at_finish(self, sm: ApplianceStateMachine) -> None:
        """cycle_duration_seconds stops growing once the cycle ends."""
        sm.update(ABOVE_START, _t(0))
        _feed(sm, QUIET, 10, FINISHED_WINDOW)
        frozen = sm.cycle_duration_seconds
        _feed(sm, QUIET, FINISHED_WINDOW + 20, 600)
        assert sm.cycle_duration_seconds == pytest.approx(frozen)


class TestPostCycle:
    """The optional phase between a finished programme and a quiet appliance."""

    def test_enters_post_cycle(self, post_sm: ApplianceStateMachine) -> None:
        """Draw under the post-cycle budget ends the working phase."""
        end = _run_cycle(post_sm)
        _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        assert post_sm.state is ApplianceState.POST_CYCLE

    def test_post_cycle_counts_as_finished(self, post_sm: ApplianceStateMachine) -> None:
        """is_finished covers POST_CYCLE — the load is ready at that point."""
        end = _run_cycle(post_sm)
        _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        assert post_sm.is_finished
        assert post_sm.is_post_cycle
        assert not post_sm.is_running

    def test_counts_the_cycle_once(self, post_sm: ApplianceStateMachine) -> None:
        """Passing RUNNING → POST_CYCLE → FINISHED counts a single cycle."""
        end = _run_cycle(post_sm)
        end = _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        assert post_sm.cycle_count == 1
        _feed(post_sm, QUIET, end, FINISHED_WINDOW)
        assert post_sm.state is ApplianceState.FINISHED
        assert post_sm.cycle_count == 1

    def test_duration_freezes_but_energy_runs_on(
        self, post_sm: ApplianceStateMachine
    ) -> None:
        """Duration stops when the work does; energy keeps counting to FINISHED."""
        end = _run_cycle(post_sm)
        end = _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        duration = post_sm.cycle_duration_seconds
        energy = post_sm.cycle_energy_kwh
        end = _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        assert post_sm.cycle_duration_seconds == pytest.approx(duration)
        assert post_sm.cycle_energy_kwh > energy

    def test_energy_freezes_at_finished(self, post_sm: ApplianceStateMachine) -> None:
        """Once FINISHED, the cycle's energy stops moving."""
        end = _run_cycle(post_sm)
        end = _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        end = _feed(post_sm, QUIET, end, FINISHED_WINDOW)
        assert post_sm.state is ApplianceState.FINISHED
        frozen = post_sm.cycle_energy_kwh
        _feed(post_sm, QUIET, end, FINISHED_WINDOW)
        assert post_sm.cycle_energy_kwh == pytest.approx(frozen)

    def test_reaches_finished_when_quiet(self, post_sm: ApplianceStateMachine) -> None:
        """A quiet window after the post-cycle phase reaches FINISHED."""
        end = _run_cycle(post_sm)
        end = _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        _feed(post_sm, QUIET, end, FINISHED_WINDOW)
        assert post_sm.state is ApplianceState.FINISHED

    def test_post_cycle_draw_does_not_reach_finished(
        self, post_sm: ApplianceStateMachine
    ) -> None:
        """The appliance stays in POST_CYCLE while it keeps drawing."""
        end = _run_cycle(post_sm)
        _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW * 3)
        assert post_sm.state is ApplianceState.POST_CYCLE

    def test_never_restarts_from_post_cycle(
        self, post_sm: ApplianceStateMachine
    ) -> None:
        """FINISHED is the only way out — draw alone cannot start a new cycle.

        The post-cycle draw of a washing machine sits above start_threshold, so
        judging a restart on live power would flap between the two states.
        """
        end = _run_cycle(post_sm)
        end = _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        _feed(post_sm, WORKING, end, POST_CYCLE_WINDOW * 2)
        assert post_sm.state is ApplianceState.POST_CYCLE
        assert post_sm.cycle_count == 1

    def test_disabled_goes_straight_to_finished(
        self, sm: ApplianceStateMachine
    ) -> None:
        """With the phase off, the same trace ends in FINISHED."""
        end = _run_cycle(sm)
        _feed(sm, QUIET, end, FINISHED_WINDOW)
        assert sm.state is ApplianceState.FINISHED
        assert not sm.is_post_cycle


class TestFinishedTransitions:
    """Transitions out of FINISHED."""

    @pytest.fixture
    def finished_sm(self, sm: ApplianceStateMachine) -> ApplianceStateMachine:
        """Return a state machine in FINISHED state."""
        end = _run_cycle(sm)
        _feed(sm, QUIET, end, FINISHED_WINDOW)
        assert sm.state is ApplianceState.FINISHED
        return sm

    def test_starts_new_cycle_at_threshold(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """Power at start_threshold starts a new cycle from FINISHED."""
        finished_sm.update(START_THRESHOLD, _t(10_000))
        assert finished_sm.state is ApplianceState.RUNNING

    def test_stays_finished_below_threshold(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """Power below start_threshold keeps state FINISHED."""
        finished_sm.update(QUIET, _t(10_000))
        assert finished_sm.state is ApplianceState.FINISHED

    def test_cycle_duration_resets_on_new_cycle(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """A new cycle zeroes the duration of the previous one."""
        finished_sm.update(ABOVE_START, _t(10_000))
        assert finished_sm.cycle_duration_seconds == 0.0

    def test_cycle_start_updated_on_new_cycle(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """cycle_start moves to the new cycle's transition timestamp."""
        finished_sm.update(ABOVE_START, _t(10_000))
        assert finished_sm.cycle_start == _t(10_000)

    def test_total_operating_does_not_accumulate_while_finished(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """Operating time does not grow in FINISHED."""
        before = finished_sm.total_operating_seconds
        _feed(finished_sm, QUIET, 10_000, 600)
        assert finished_sm.total_operating_seconds == pytest.approx(before)


class TestStartHysteresis:
    """start_delay suppresses brief spikes that are not a real cycle start."""

    START_DELAY: float = 60.0

    @pytest.fixture
    def delayed_sm(self) -> ApplianceStateMachine:
        """Return a state machine with a start delay configured."""
        return ApplianceStateMachine(
            start_threshold=START_THRESHOLD,
            start_delay_seconds=self.START_DELAY,
            finished_window_seconds=FINISHED_WINDOW,
            finished_energy_threshold_wh=FINISHED_ENERGY_WH,
        )

    def test_stays_idle_before_delay_expires(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """A spike shorter than the delay does not start a cycle."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(ABOVE_START, _t(self.START_DELAY - 1))
        assert delayed_sm.state is ApplianceState.IDLE

    def test_transitions_to_running_after_delay(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """Sustained power past the delay starts the cycle."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(ABOVE_START, _t(self.START_DELAY))
        assert delayed_sm.state is ApplianceState.RUNNING

    def test_delay_resets_on_power_drop(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """A power drop below threshold resets the hysteresis timer."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(QUIET, _t(self.START_DELAY / 2))
        delayed_sm.update(ABOVE_START, _t(self.START_DELAY / 2 + 1))
        delayed_sm.update(ABOVE_START, _t(self.START_DELAY))
        assert delayed_sm.state is ApplianceState.IDLE

    def test_zero_delay_transitions_immediately(self, sm: ApplianceStateMachine) -> None:
        """The default of no delay starts on the first qualifying sample."""
        sm.update(ABOVE_START, _t(0))
        assert sm.state is ApplianceState.RUNNING


class TestReset:
    """reset() forces the machine back to IDLE regardless of current state."""

    def test_reset_from_running(self, sm: ApplianceStateMachine) -> None:
        """Reset while RUNNING returns the machine to IDLE."""
        sm.update(ABOVE_START, _t(0))
        sm.reset()
        assert sm.state is ApplianceState.IDLE

    def test_reset_from_post_cycle(self, post_sm: ApplianceStateMachine) -> None:
        """Reset while POST_CYCLE returns the machine to IDLE."""
        end = _run_cycle(post_sm)
        _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        post_sm.reset()
        assert post_sm.state is ApplianceState.IDLE

    def test_reset_clears_cycle_duration(self, sm: ApplianceStateMachine) -> None:
        """Reset zeroes the cycle duration."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(60))
        sm.reset()
        assert sm.cycle_duration_seconds == 0.0

    def test_reset_clears_cycle_start(self, sm: ApplianceStateMachine) -> None:
        """Reset clears the cycle start timestamp."""
        sm.update(ABOVE_START, _t(0))
        sm.reset()
        assert sm.cycle_start is None

    def test_reset_preserves_cycle_count(self, sm: ApplianceStateMachine) -> None:
        """reset() does not zero the cycle counter."""
        end = _run_cycle(sm)
        _feed(sm, QUIET, end, FINISHED_WINDOW)
        sm.reset()
        assert sm.cycle_count == 1

    def test_reset_preserves_total_operating_time(
        self, sm: ApplianceStateMachine
    ) -> None:
        """reset() does not clear total_operating_seconds."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(60))
        total_before = sm.total_operating_seconds
        sm.reset()
        assert sm.total_operating_seconds == pytest.approx(total_before)

    def test_reset_clears_the_window(self, sm: ApplianceStateMachine) -> None:
        """A cycle started right after a reset cannot finish on stale samples."""
        _feed(sm, QUIET, 0, FINISHED_WINDOW * 2)
        sm.reset()
        sm.update(ABOVE_START, _t(FINISHED_WINDOW * 2 + 10))
        sm.update(QUIET, _t(FINISHED_WINDOW * 2 + 20))
        assert sm.state is ApplianceState.RUNNING


class TestUnloaded:
    """mark_unloaded() acknowledges a finished cycle and is inert elsewhere."""

    def _finish(self, sm: ApplianceStateMachine) -> float:
        """Drive sm through one complete cycle into FINISHED; return the end offset."""
        end = _run_cycle(sm)
        return _feed(sm, QUIET, end, FINISHED_WINDOW)

    def test_finished_becomes_idle(self, sm: ApplianceStateMachine) -> None:
        """FINISHED → IDLE."""
        self._finish(sm)
        sm.mark_unloaded()
        assert sm.state is ApplianceState.IDLE

    def test_running_is_untouched(self, sm: ApplianceStateMachine) -> None:
        """A press while RUNNING must not cut the cycle short."""
        sm.update(ABOVE_START, _t(0))
        sm.mark_unloaded()
        assert sm.state is ApplianceState.RUNNING

    def test_idle_is_untouched(self, sm: ApplianceStateMachine) -> None:
        """A press while IDLE is a no-op."""
        sm.update(QUIET, _t(0))
        sm.mark_unloaded()
        assert sm.state is ApplianceState.IDLE

    def test_keeps_last_cycle_metrics(self, sm: ApplianceStateMachine) -> None:
        """The last cycle's duration, energy and start timestamp are kept."""
        self._finish(sm)
        duration_before = sm.cycle_duration_seconds
        energy_before = sm.cycle_energy_kwh
        sm.mark_unloaded()
        assert sm.cycle_duration_seconds == pytest.approx(duration_before)
        assert sm.cycle_energy_kwh == pytest.approx(energy_before)
        assert sm.cycle_start is not None

    def test_preserves_cycle_count(self, sm: ApplianceStateMachine) -> None:
        """Acknowledging a cycle does not un-count it."""
        self._finish(sm)
        sm.mark_unloaded()
        assert sm.cycle_count == 1

    def test_while_disconnected_resumes_idle(self, sm: ApplianceStateMachine) -> None:
        """Unloaded during a source outage: reconnect resumes IDLE, not FINISHED."""
        end = self._finish(sm)
        sm.mark_disconnected()
        sm.mark_unloaded()
        assert sm.state is ApplianceState.DISCONNECTED
        assert sm.state_before_disconnect is ApplianceState.IDLE
        sm.update(QUIET, _t(end + 500))
        assert sm.state is ApplianceState.IDLE

    def test_while_disconnected_from_running_is_inert(
        self, sm: ApplianceStateMachine
    ) -> None:
        """A disconnect mid-cycle still resumes RUNNING after a stray press."""
        sm.update(ABOVE_START, _t(0))
        sm.mark_disconnected()
        sm.mark_unloaded()
        assert sm.state_before_disconnect is ApplianceState.RUNNING

    def test_new_cycle_starts_normally_after(self, sm: ApplianceStateMachine) -> None:
        """A fresh cycle begins as usual once the appliance is unloaded."""
        end = self._finish(sm)
        sm.mark_unloaded()
        sm.update(ABOVE_START, _t(end + 300))
        assert sm.state is ApplianceState.RUNNING
        assert sm.cycle_duration_seconds == 0.0


class TestCycleCount:
    """cycle_count increments when a cycle ends and is zeroed on demand."""

    def _finish_cycle(self, sm: ApplianceStateMachine, start: float = 0.0) -> float:
        """Drive sm through one complete cycle; return the end offset."""
        end = _run_cycle(sm, start)
        return _feed(sm, QUIET, end, FINISHED_WINDOW)

    def test_increments_on_finished(self, sm: ApplianceStateMachine) -> None:
        """cycle_count becomes 1 when the first cycle ends."""
        self._finish_cycle(sm)
        assert sm.cycle_count == 1

    def test_increments_across_multiple_cycles(self, sm: ApplianceStateMachine) -> None:
        """cycle_count accumulates across back-to-back cycles."""
        end = self._finish_cycle(sm)
        end = self._finish_cycle(sm, end + 60)
        self._finish_cycle(sm, end + 60)
        assert sm.cycle_count == 3

    def test_does_not_increment_on_reset_from_running(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Resetting mid-cycle does not count as a completed cycle."""
        sm.update(ABOVE_START, _t(0))
        sm.reset()
        assert sm.cycle_count == 0

    def test_reset_cycle_count_zeroes_counter(self, sm: ApplianceStateMachine) -> None:
        """reset_cycle_count() brings the counter back to zero."""
        self._finish_cycle(sm)
        sm.reset_cycle_count()
        assert sm.cycle_count == 0

    def test_reset_cycle_count_leaves_state_intact(
        self, sm: ApplianceStateMachine
    ) -> None:
        """reset_cycle_count() does not affect the current machine state."""
        self._finish_cycle(sm)
        sm.reset_cycle_count()
        assert sm.state is ApplianceState.FINISHED


class TestTotalOperatingTime:
    """total_operating_seconds accumulates RUNNING time and survives resets."""

    def test_accumulates_running_time(self, sm: ApplianceStateMachine) -> None:
        """Operating time grows while RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        assert sm.total_operating_seconds == pytest.approx(30.0)

    def test_accumulates_during_low_draw_phase(self, sm: ApplianceStateMachine) -> None:
        """Operating time grows even when power is low — state is still RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(QUIET, _t(10))
        sm.update(QUIET, _t(40))
        assert sm.state is ApplianceState.RUNNING
        assert sm.total_operating_seconds == pytest.approx(40.0)

    def test_does_not_accumulate_while_idle(self, sm: ApplianceStateMachine) -> None:
        """Operating time does not grow while IDLE."""
        sm.update(QUIET, _t(0))
        sm.update(QUIET, _t(9999))
        assert sm.total_operating_seconds == 0.0

    def test_does_not_accumulate_during_post_cycle(
        self, post_sm: ApplianceStateMachine
    ) -> None:
        """POST_CYCLE is not working time."""
        end = _run_cycle(post_sm)
        end = _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        before = post_sm.total_operating_seconds
        _feed(post_sm, POST_CYCLE, end, 600)
        assert post_sm.total_operating_seconds == pytest.approx(before)


class TestEnergy:
    """cycle_energy_kwh and total_energy_kwh integrate power over time."""

    POWER_W = 3600.0  # 3600 W for 1 s = 1 Wh

    def test_initial_zero(self, sm: ApplianceStateMachine) -> None:
        """Both energy counters start at zero."""
        assert sm.cycle_energy_kwh == 0.0
        assert sm.total_energy_kwh == 0.0

    def test_no_integration_first_tick(self, sm: ApplianceStateMachine) -> None:
        """First update never integrates (no prior reading to integrate from)."""
        sm.update(self.POWER_W, _t(0))
        assert sm.cycle_energy_kwh == 0.0
        assert sm.total_energy_kwh == 0.0

    def test_constant_power_running(self, sm: ApplianceStateMachine) -> None:
        """Constant 3600 W for 10 s while RUNNING → 0.01 kWh."""
        sm.update(self.POWER_W, _t(0))
        sm.update(self.POWER_W, _t(10))
        assert sm.cycle_energy_kwh == pytest.approx(0.01)
        assert sm.total_energy_kwh == pytest.approx(0.01)

    def test_trapezoidal_with_varying_power(self, sm: ApplianceStateMachine) -> None:
        """Trapezoidal: average of (1000+2000)/2 = 1500 W for 10 s."""
        sm.update(1000.0, _t(0))
        sm.update(2000.0, _t(10))
        assert sm.cycle_energy_kwh == pytest.approx(15000 / 3_600_000.0)

    def test_cycle_energy_does_not_integrate_while_idle(
        self, sm: ApplianceStateMachine
    ) -> None:
        """cycle_energy_kwh stays zero while in IDLE."""
        sm.update(QUIET, _t(0))
        sm.update(QUIET, _t(3600))
        assert sm.cycle_energy_kwh == 0.0

    def test_total_energy_integrates_while_idle(
        self, sm: ApplianceStateMachine
    ) -> None:
        """total_energy_kwh accumulates standby consumption during IDLE."""
        sm.update(QUIET, _t(0))
        sm.update(QUIET, _t(3600))
        assert sm.total_energy_kwh == pytest.approx(QUIET * 3600 / 3_600_000.0)

    def test_cycle_energy_resets_on_new_cycle(self, sm: ApplianceStateMachine) -> None:
        """A new cycle starts cycle_energy_kwh from zero."""
        end = _run_cycle(sm)
        _feed(sm, QUIET, end, FINISHED_WINDOW)
        sm.update(ABOVE_START, _t(20_000))
        assert sm.cycle_energy_kwh == 0.0

    def test_total_energy_survives_new_cycle(self, sm: ApplianceStateMachine) -> None:
        """total_energy_kwh is never cleared by a new cycle."""
        end = _run_cycle(sm)
        _feed(sm, QUIET, end, FINISHED_WINDOW)
        before = sm.total_energy_kwh
        sm.update(ABOVE_START, _t(20_000))
        assert sm.total_energy_kwh >= before

    def test_cycle_energy_cleared_by_reset(self, sm: ApplianceStateMachine) -> None:
        """reset() zeroes the current cycle's energy."""
        sm.update(self.POWER_W, _t(0))
        sm.update(self.POWER_W, _t(10))
        sm.reset()
        assert sm.cycle_energy_kwh == 0.0

    def test_total_energy_survives_reset(self, sm: ApplianceStateMachine) -> None:
        """reset() does not clear the lifetime energy total."""
        sm.update(self.POWER_W, _t(0))
        sm.update(self.POWER_W, _t(10))
        sm.reset()
        assert sm.total_energy_kwh == pytest.approx(0.01)


class TestRestoreSnapshot:
    """Persisted state and totals are restored without side effects."""

    def test_defaults_when_nothing_provided(self, sm: ApplianceStateMachine) -> None:
        """Restoring an empty snapshot leaves a pristine machine."""
        sm.restore_snapshot()
        assert sm.state is ApplianceState.IDLE
        assert sm.cycle_count == 0
        assert sm.total_operating_seconds == 0.0
        assert sm.total_energy_kwh == 0.0
        assert sm.cycle_start is None

    def test_restores_running_state(self, sm: ApplianceStateMachine) -> None:
        """A RUNNING snapshot comes back as RUNNING with its totals."""
        sm.restore_snapshot(
            state=ApplianceState.RUNNING,
            cycle_count=4,
            total_operating_seconds=1234.0,
            total_energy_kwh=2.5,
            cycle_start=_t(0),
            cycle_duration_seconds=60.0,
        )
        assert sm.state is ApplianceState.RUNNING
        assert sm.cycle_count == 4
        assert sm.total_operating_seconds == pytest.approx(1234.0)

    def test_restored_post_cycle_state(self, post_sm: ApplianceStateMachine) -> None:
        """POST_CYCLE survives a restart."""
        post_sm.restore_snapshot(state=ApplianceState.POST_CYCLE, cycle_count=2)
        assert post_sm.state is ApplianceState.POST_CYCLE
        assert post_sm.is_finished

    def test_restored_running_needs_a_full_window(
        self, sm: ApplianceStateMachine
    ) -> None:
        """After a restart the cycle cannot finish until a window is collected."""
        sm.restore_snapshot(state=ApplianceState.RUNNING, cycle_start=_t(0))
        _feed(sm, QUIET, 0, FINISHED_WINDOW - 60)
        assert sm.state is ApplianceState.RUNNING
        _feed(sm, QUIET, FINISHED_WINDOW - 60, 120)
        assert sm.state is ApplianceState.FINISHED

    def test_first_tick_after_restore_does_not_inflate_totals(
        self, sm: ApplianceStateMachine
    ) -> None:
        """The first sample after a restore integrates nothing."""
        sm.restore_snapshot(state=ApplianceState.RUNNING, total_energy_kwh=1.0)
        sm.update(WORKING, _t(9999))
        assert sm.total_energy_kwh == pytest.approx(1.0)


class TestDisconnected:
    """Source outages pause the machine without corrupting totals."""

    def test_mark_disconnected_from_running(self, sm: ApplianceStateMachine) -> None:
        """The previous state is remembered while disconnected."""
        sm.update(ABOVE_START, _t(0))
        sm.mark_disconnected()
        assert sm.state is ApplianceState.DISCONNECTED
        assert sm.state_before_disconnect is ApplianceState.RUNNING

    def test_reconnect_restores_previous_state(self, sm: ApplianceStateMachine) -> None:
        """The next sample after an outage resumes the prior state."""
        sm.update(ABOVE_START, _t(0))
        sm.mark_disconnected()
        sm.update(WORKING, _t(600))
        assert sm.state is ApplianceState.RUNNING

    def test_disconnect_does_not_integrate_energy_across_gap(
        self, sm: ApplianceStateMachine
    ) -> None:
        """No energy is attributed to the silent period."""
        sm.update(WORKING, _t(0))
        sm.mark_disconnected()
        before = sm.total_energy_kwh
        sm.update(WORKING, _t(36_000))
        assert sm.total_energy_kwh == pytest.approx(before)

    def test_disconnect_clears_the_window(self, sm: ApplianceStateMachine) -> None:
        """Samples from before an outage cannot finish the cycle after it."""
        sm.update(ABOVE_START, _t(0))
        _feed(sm, QUIET, 10, FINISHED_WINDOW - 60)
        sm.mark_disconnected()
        sm.update(QUIET, _t(FINISHED_WINDOW))
        sm.update(QUIET, _t(FINISHED_WINDOW + 10))
        assert sm.state is ApplianceState.RUNNING

    def test_repeated_mark_disconnected_is_idempotent(
        self, sm: ApplianceStateMachine
    ) -> None:
        """A second disconnect does not overwrite the remembered state."""
        sm.update(ABOVE_START, _t(0))
        sm.mark_disconnected()
        sm.mark_disconnected()
        assert sm.state_before_disconnect is ApplianceState.RUNNING


class TestFullCycle:
    """End-to-end runs through the whole state graph."""

    def test_complete_cycle(self, sm: ApplianceStateMachine) -> None:
        """IDLE → RUNNING → FINISHED → RUNNING again."""
        assert sm.state is ApplianceState.IDLE
        end = _run_cycle(sm)
        assert sm.state is ApplianceState.RUNNING
        end = _feed(sm, QUIET, end, FINISHED_WINDOW)
        assert sm.state is ApplianceState.FINISHED
        assert sm.cycle_count == 1
        sm.update(ABOVE_START, _t(end + 600))
        assert sm.state is ApplianceState.RUNNING

    def test_complete_cycle_with_post_phase(
        self, post_sm: ApplianceStateMachine
    ) -> None:
        """IDLE → RUNNING → POST_CYCLE → FINISHED, counted once."""
        end = _run_cycle(post_sm)
        end = _feed(post_sm, POST_CYCLE, end, POST_CYCLE_WINDOW)
        assert post_sm.state is ApplianceState.POST_CYCLE
        _feed(post_sm, QUIET, end, FINISHED_WINDOW)
        assert post_sm.state is ApplianceState.FINISHED
        assert post_sm.cycle_count == 1
