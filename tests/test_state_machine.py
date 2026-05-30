"""Tests for the ApplianceStateMachine."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.appliance_monitor.state_machine import (
    ApplianceState,
    ApplianceStateMachine,
)

START_THRESHOLD: float = 10.0
IDLE_THRESHOLD: float = 5.0
IDLE_TIMEOUT_SECS: float = 60.0

T0 = datetime(2024, 1, 1)  # noqa: DTZ001

ABOVE_START: float = START_THRESHOLD + 1.0
BELOW_IDLE: float = IDLE_THRESHOLD - 1.0


def _t(seconds: float) -> datetime:
    """Return T0 offset by *seconds*."""
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def sm() -> ApplianceStateMachine:
    """Return a fresh state machine with standard thresholds."""
    return ApplianceStateMachine(
        start_threshold=START_THRESHOLD,
        idle_threshold=IDLE_THRESHOLD,
        idle_timeout_seconds=IDLE_TIMEOUT_SECS,
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
    """Transitions out of IDLE."""

    def test_stays_idle_at_threshold(self, sm: ApplianceStateMachine) -> None:
        """Power at start_threshold does not leave IDLE (strictly greater-than)."""
        sm.update(START_THRESHOLD, _t(0))
        assert sm.state is ApplianceState.IDLE

    def test_stays_idle_below_threshold(self, sm: ApplianceStateMachine) -> None:
        """Power below start_threshold keeps state IDLE."""
        sm.update(BELOW_IDLE, _t(0))
        assert sm.state is ApplianceState.IDLE

    def test_transitions_to_running(self, sm: ApplianceStateMachine) -> None:
        """Power strictly above start_threshold transitions IDLE→RUNNING."""
        sm.update(ABOVE_START, _t(0))
        assert sm.state is ApplianceState.RUNNING
        assert sm.is_running

    def test_cycle_duration_zero_on_start(self, sm: ApplianceStateMachine) -> None:
        """cycle_duration_seconds is zero on IDLE→RUNNING transition."""
        sm.update(ABOVE_START, _t(30))
        assert sm.cycle_duration_seconds == 0.0

    def test_cycle_start_set_on_running(self, sm: ApplianceStateMachine) -> None:
        """cycle_start is set to the transition timestamp on IDLE→RUNNING."""
        sm.update(ABOVE_START, _t(30))
        assert sm.cycle_start == _t(30)

    def test_first_update_never_accumulates_operating_time(
        self, sm: ApplianceStateMachine
    ) -> None:
        """
        No operating time is accumulated on the first update.

        Regardless of timestamp.
        """
        sm.update(ABOVE_START, _t(9999))
        assert sm.total_operating_seconds == 0.0


class TestRunningTransitions:
    """Transitions out of RUNNING."""

    def test_stays_running_at_idle_threshold(self, sm: ApplianceStateMachine) -> None:
        """Power at idle_threshold does not leave RUNNING (strictly less-than)."""
        sm.update(ABOVE_START, _t(0))
        sm.update(IDLE_THRESHOLD, _t(10))
        assert sm.state is ApplianceState.RUNNING

    def test_stays_running_above_idle_threshold(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Power above idle_threshold keeps state RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(10))
        assert sm.state is ApplianceState.RUNNING

    def test_transitions_to_paused(self, sm: ApplianceStateMachine) -> None:
        """Power strictly below idle_threshold transitions RUNNING→PAUSED."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        assert sm.state is ApplianceState.PAUSED

    def test_cycle_duration_accumulates(self, sm: ApplianceStateMachine) -> None:
        """cycle_duration_seconds grows by elapsed seconds while RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        assert sm.cycle_duration_seconds == pytest.approx(30.0)

    def test_cycle_duration_cumulative_across_updates(
        self, sm: ApplianceStateMachine
    ) -> None:
        """cycle_duration_seconds sums elapsed time across multiple RUNNING updates."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        sm.update(ABOVE_START, _t(50))
        assert sm.cycle_duration_seconds == pytest.approx(50.0)

    def test_cycle_duration_includes_interval_to_paused(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Elapsed time up to the RUNNING→PAUSED transition is counted."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(20))
        assert sm.cycle_duration_seconds == pytest.approx(20.0)

    def test_total_operating_accumulates_while_running(
        self, sm: ApplianceStateMachine
    ) -> None:
        """total_operating_seconds accumulates while RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        assert sm.total_operating_seconds == pytest.approx(30.0)


class TestPausedTransitions:
    """Transitions out of PAUSED."""

    @pytest.fixture
    def paused_sm(self, sm: ApplianceStateMachine) -> ApplianceStateMachine:
        """Return a state machine in PAUSED state (paused at t=10)."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        return sm

    def test_stays_paused_within_timeout(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """State stays PAUSED while below threshold and timeout has not expired."""
        paused_sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS - 1))
        assert paused_sm.state is ApplianceState.PAUSED

    def test_stays_paused_exactly_at_timeout(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """Timeout is strictly greater-than, so exactly at the boundary stays PAUSED."""
        paused_sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS))
        assert paused_sm.state is ApplianceState.PAUSED

    def test_transitions_to_finished_after_timeout(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """State becomes FINISHED once idle_timeout_seconds is exceeded."""
        paused_sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        assert paused_sm.state is ApplianceState.FINISHED
        assert paused_sm.is_finished
        assert not paused_sm.is_running

    def test_resumes_running_on_power_recovery(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """Power above start_threshold transitions PAUSED→RUNNING."""
        paused_sm.update(ABOVE_START, _t(20))
        assert paused_sm.state is ApplianceState.RUNNING
        assert paused_sm.is_running

    def test_pause_start_cleared_on_resume(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """_pause_start is cleared when resuming from PAUSED to RUNNING."""
        paused_sm.update(ABOVE_START, _t(20))
        assert paused_sm._pause_start is None

    def test_cycle_duration_continues_while_paused(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """
        cycle_duration_seconds keeps growing while PAUSED.

        Appliance is still active during a pause.
        """
        paused_sm.update(BELOW_IDLE, _t(10 + 30))
        assert paused_sm.cycle_duration_seconds == pytest.approx(40.0)

    def test_total_operating_accumulates_while_paused(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """total_operating_seconds accumulates during PAUSED state."""
        operating_at_pause = paused_sm.total_operating_seconds
        paused_sm.update(BELOW_IDLE, _t(10 + 30))
        assert paused_sm.total_operating_seconds == pytest.approx(
            operating_at_pause + 30.0
        )

    def test_cycle_duration_after_recovery(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """
        cycle_duration_seconds is wall-clock from cycle start.

        Measured across pause and resume.
        """
        paused_sm.update(ABOVE_START, _t(20))  # resume
        paused_sm.update(ABOVE_START, _t(35))  # 15 s more running
        assert paused_sm.cycle_duration_seconds == pytest.approx(35.0)


class TestFinishedTransitions:
    """Transitions out of FINISHED."""

    @pytest.fixture
    def finished_sm(self, sm: ApplianceStateMachine) -> ApplianceStateMachine:
        """Return a state machine in FINISHED state."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        return sm

    def test_stays_finished_at_threshold(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """Power exactly at start_threshold does not leave FINISHED."""
        finished_sm.update(START_THRESHOLD, _t(200))
        assert finished_sm.state is ApplianceState.FINISHED

    def test_stays_finished_below_threshold(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """Power below start_threshold keeps state FINISHED."""
        finished_sm.update(BELOW_IDLE, _t(200))
        assert finished_sm.state is ApplianceState.FINISHED

    def test_new_cycle_transitions_to_running(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """Power above start_threshold starts a new cycle: FINISHED→RUNNING."""
        finished_sm.update(ABOVE_START, _t(200))
        assert finished_sm.state is ApplianceState.RUNNING

    def test_cycle_duration_frozen_at_finished(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """cycle_duration_seconds does not change while in FINISHED state."""
        frozen = finished_sm.cycle_duration_seconds
        finished_sm.update(BELOW_IDLE, _t(200))
        assert finished_sm.cycle_duration_seconds == pytest.approx(frozen)

    def test_cycle_duration_resets_on_new_cycle(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """cycle_duration_seconds is zeroed when a new cycle starts from FINISHED."""
        finished_sm.update(ABOVE_START, _t(200))
        assert finished_sm.cycle_duration_seconds == 0.0

    def test_cycle_start_updated_on_new_cycle(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """cycle_start is updated to the new cycle's start time."""
        finished_sm.update(ABOVE_START, _t(200))
        assert finished_sm.cycle_start == _t(200)

    def test_pause_start_cleared_on_new_cycle(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """_pause_start is cleared when a new cycle starts from FINISHED."""
        finished_sm.update(ABOVE_START, _t(200))
        assert finished_sm._pause_start is None

    def test_total_operating_does_not_accumulate_while_finished(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """total_operating_seconds does not grow while in FINISHED state."""
        total_at_finish = finished_sm.total_operating_seconds
        finished_sm.update(BELOW_IDLE, _t(200))
        assert finished_sm.total_operating_seconds == pytest.approx(total_at_finish)


class TestStartHysteresis:
    """start_delay_seconds prevents premature IDLE/FINISHED→RUNNING transitions."""

    START_DELAY: float = 60.0

    @pytest.fixture
    def delayed_sm(self) -> ApplianceStateMachine:
        """State machine with a 60-second start delay."""
        return ApplianceStateMachine(
            start_threshold=START_THRESHOLD,
            idle_threshold=IDLE_THRESHOLD,
            idle_timeout_seconds=IDLE_TIMEOUT_SECS,
            start_delay_seconds=self.START_DELAY,
        )

    def test_stays_idle_before_delay_expires(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """Power above threshold but delay not yet elapsed keeps state IDLE."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(ABOVE_START, _t(self.START_DELAY - 1))
        assert delayed_sm.state is ApplianceState.IDLE

    def test_transitions_to_running_after_delay(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """State becomes RUNNING once power stays above threshold for the full delay."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(ABOVE_START, _t(self.START_DELAY))
        assert delayed_sm.state is ApplianceState.RUNNING

    def test_delay_resets_on_power_drop(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """A power drop below threshold resets the hysteresis timer."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(BELOW_IDLE, _t(self.START_DELAY - 1))  # drops before delay
        delayed_sm.update(ABOVE_START, _t(self.START_DELAY))  # back up — timer resets
        assert delayed_sm.state is ApplianceState.IDLE

    def test_zero_delay_transitions_immediately(self) -> None:
        """With start_delay_seconds=0 (default), IDLE→RUNNING fires immediately."""
        sm = ApplianceStateMachine(
            start_threshold=START_THRESHOLD,
            idle_threshold=IDLE_THRESHOLD,
            idle_timeout_seconds=IDLE_TIMEOUT_SECS,
            start_delay_seconds=0,
        )
        sm.update(ABOVE_START, _t(0))
        assert sm.state is ApplianceState.RUNNING

    def test_finished_to_running_respects_delay(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """FINISHED→RUNNING also requires the start delay to elapse."""
        t_run = self.START_DELAY
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(ABOVE_START, _t(t_run))
        delayed_sm.update(BELOW_IDLE, _t(t_run + 10))
        delayed_sm.update(BELOW_IDLE, _t(t_run + 10 + IDLE_TIMEOUT_SECS + 1))
        delayed_sm.update(ABOVE_START, _t(t_run + 200))  # delay not yet elapsed
        assert delayed_sm.state is ApplianceState.FINISHED

    def test_default_has_no_delay(self) -> None:
        """start_delay_seconds defaults to zero — same as explicitly passing 0."""
        sm_explicit = ApplianceStateMachine(
            start_threshold=START_THRESHOLD,
            idle_threshold=IDLE_THRESHOLD,
            idle_timeout_seconds=IDLE_TIMEOUT_SECS,
            start_delay_seconds=0,
        )
        sm_default = ApplianceStateMachine(
            start_threshold=START_THRESHOLD,
            idle_threshold=IDLE_THRESHOLD,
            idle_timeout_seconds=IDLE_TIMEOUT_SECS,
        )
        sm_explicit.update(ABOVE_START, _t(0))
        sm_default.update(ABOVE_START, _t(0))
        assert sm_explicit.state == sm_default.state


class TestPauseHysteresis:
    """pause_delay_seconds prevents premature RUNNING→PAUSED transitions."""

    PAUSE_DELAY: float = 30.0

    @pytest.fixture
    def delayed_sm(self) -> ApplianceStateMachine:
        """State machine with a 30-second pause delay."""
        return ApplianceStateMachine(
            start_threshold=START_THRESHOLD,
            idle_threshold=IDLE_THRESHOLD,
            idle_timeout_seconds=IDLE_TIMEOUT_SECS,
            pause_delay_seconds=self.PAUSE_DELAY,
        )

    def test_stays_running_before_pause_delay_expires(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """Brief power dip below idle threshold does not immediately pause."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(BELOW_IDLE, _t(10))
        delayed_sm.update(BELOW_IDLE, _t(10 + self.PAUSE_DELAY - 1))
        assert delayed_sm.state is ApplianceState.RUNNING

    def test_transitions_to_paused_after_delay(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """State becomes PAUSED once power stays low for the full pause delay."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(BELOW_IDLE, _t(10))
        delayed_sm.update(BELOW_IDLE, _t(10 + self.PAUSE_DELAY))
        assert delayed_sm.state is ApplianceState.PAUSED

    def test_pause_delay_resets_on_power_recovery(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """A power recovery above idle threshold resets the pause hysteresis timer."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(BELOW_IDLE, _t(10))
        delayed_sm.update(ABOVE_START, _t(10 + self.PAUSE_DELAY - 1))  # recovers
        delayed_sm.update(BELOW_IDLE, _t(10 + self.PAUSE_DELAY))  # dip resets timer
        assert delayed_sm.state is ApplianceState.RUNNING

    def test_zero_pause_delay_transitions_immediately(self) -> None:
        """With pause_delay_seconds=0 (default), RUNNING→PAUSED fires immediately."""
        sm = ApplianceStateMachine(
            start_threshold=START_THRESHOLD,
            idle_threshold=IDLE_THRESHOLD,
            idle_timeout_seconds=IDLE_TIMEOUT_SECS,
            pause_delay_seconds=0,
        )
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        assert sm.state is ApplianceState.PAUSED

    def test_cycle_duration_not_lost_during_pending_pause(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """cycle_duration_seconds keeps accumulating during a pending pause."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(ABOVE_START, _t(20))  # 20 s running
        delayed_sm.update(BELOW_IDLE, _t(30))  # dip — still RUNNING
        delayed_sm.update(BELOW_IDLE, _t(40))  # still within delay
        assert delayed_sm.state is ApplianceState.RUNNING
        assert delayed_sm.cycle_duration_seconds == pytest.approx(40.0)


class TestReset:
    """reset() forces the machine back to IDLE regardless of current state."""

    def test_reset_from_running(self, sm: ApplianceStateMachine) -> None:
        """Reset while RUNNING returns the machine to IDLE."""
        sm.update(ABOVE_START, _t(0))
        assert sm.state is ApplianceState.RUNNING
        sm.reset()
        assert sm.state is ApplianceState.IDLE

    def test_reset_from_paused(self, sm: ApplianceStateMachine) -> None:
        """Reset while PAUSED returns the machine to IDLE."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.reset()
        assert sm.state is ApplianceState.IDLE

    def test_reset_from_finished(self, sm: ApplianceStateMachine) -> None:
        """Reset while FINISHED returns the machine to IDLE."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        assert sm.state is ApplianceState.FINISHED
        sm.reset()
        assert sm.state is ApplianceState.IDLE

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

    def test_reset_clears_is_finished(self, sm: ApplianceStateMachine) -> None:
        """is_finished is False immediately after a reset."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        sm.reset()
        assert not sm.is_finished

    def test_reset_preserves_cycle_count(self, sm: ApplianceStateMachine) -> None:
        """reset() does not zero the cycle counter."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        assert sm.cycle_count == 1
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

    def test_reset_allows_normal_cycle_after(self, sm: ApplianceStateMachine) -> None:
        """A normal cycle can start immediately after a reset."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        sm.reset()
        sm.update(ABOVE_START, _t(200))
        assert sm.state is ApplianceState.RUNNING
        assert sm.cycle_duration_seconds == 0.0


class TestCycleCount:
    """cycle_count increments on FINISHED and is zeroed by reset_cycle_count()."""

    def _finish_cycle(self, sm: ApplianceStateMachine, t_offset: float = 0) -> float:
        """Drive sm through one complete cycle; return the timestamp of FINISHED."""
        t_run = t_offset
        sm.update(ABOVE_START, _t(t_run))
        sm.update(BELOW_IDLE, _t(t_run + 10))
        t_fin = t_run + 10 + IDLE_TIMEOUT_SECS + 1
        sm.update(BELOW_IDLE, _t(t_fin))
        return t_fin

    def test_increments_on_finished(self, sm: ApplianceStateMachine) -> None:
        """cycle_count becomes 1 when the first cycle reaches FINISHED."""
        self._finish_cycle(sm)
        assert sm.cycle_count == 1

    def test_increments_across_multiple_cycles(self, sm: ApplianceStateMachine) -> None:
        """cycle_count accumulates across back-to-back cycles."""
        t = self._finish_cycle(sm, t_offset=0)
        t = self._finish_cycle(sm, t_offset=t + 10)
        self._finish_cycle(sm, t_offset=t + 10)
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
        assert sm.cycle_count == 1
        sm.reset_cycle_count()
        assert sm.cycle_count == 0

    def test_reset_cycle_count_leaves_state_intact(
        self, sm: ApplianceStateMachine
    ) -> None:
        """reset_cycle_count() does not affect the current machine state."""
        self._finish_cycle(sm)
        assert sm.state is ApplianceState.FINISHED
        sm.reset_cycle_count()
        assert sm.state is ApplianceState.FINISHED

    def test_count_continues_after_reset_cycle_count(
        self, sm: ApplianceStateMachine
    ) -> None:
        """After zeroing, the counter resumes counting from zero."""
        self._finish_cycle(sm, t_offset=0)
        sm.reset_cycle_count()
        self._finish_cycle(sm, t_offset=300)
        assert sm.cycle_count == 1


class TestTotalOperatingTime:
    """total_operating_seconds accumulates RUNNING+PAUSED time and survives resets."""

    def test_accumulates_running_time(self, sm: ApplianceStateMachine) -> None:
        """Operating time grows while RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        assert sm.total_operating_seconds == pytest.approx(30.0)

    def test_accumulates_paused_time(self, sm: ApplianceStateMachine) -> None:
        """Operating time grows while PAUSED."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))  # → PAUSED
        sm.update(BELOW_IDLE, _t(40))  # 30 s in PAUSED
        assert sm.total_operating_seconds == pytest.approx(40.0)

    def test_does_not_accumulate_while_idle(self, sm: ApplianceStateMachine) -> None:
        """Operating time does not grow while IDLE."""
        sm.update(BELOW_IDLE, _t(0))
        sm.update(BELOW_IDLE, _t(9999))
        assert sm.total_operating_seconds == 0.0

    def test_survives_reset(self, sm: ApplianceStateMachine) -> None:
        """total_operating_seconds is preserved after reset()."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(60))
        sm.reset()
        assert sm.total_operating_seconds == pytest.approx(60.0)

    def test_survives_reset_cycle_count(self, sm: ApplianceStateMachine) -> None:
        """total_operating_seconds is preserved after reset_cycle_count()."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(60))
        sm.reset_cycle_count()
        assert sm.total_operating_seconds == pytest.approx(60.0)

    def test_accumulates_across_multiple_cycles(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Operating time sums across back-to-back cycles including pauses."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(50))  # 50 s running
        sm.update(BELOW_IDLE, _t(60))  # → PAUSED (10 s running counted on this tick)
        sm.update(BELOW_IDLE, _t(60 + IDLE_TIMEOUT_SECS + 1))  # → FINISHED
        total_after_first = sm.total_operating_seconds
        sm.update(ABOVE_START, _t(200))  # new cycle
        sm.update(ABOVE_START, _t(230))  # 30 s running
        assert sm.total_operating_seconds == pytest.approx(total_after_first + 30.0)


class TestFullCycle:
    """End-to-end scenarios covering the full state graph."""

    def test_complete_cycle(self, sm: ApplianceStateMachine) -> None:
        """Full cycle: IDLE→RUNNING→PAUSED→RUNNING→PAUSED→FINISHED→RUNNING."""
        sm.update(ABOVE_START, _t(0))
        assert sm.state is ApplianceState.RUNNING

        sm.update(BELOW_IDLE, _t(30))
        assert sm.state is ApplianceState.PAUSED

        sm.update(ABOVE_START, _t(45))
        assert sm.state is ApplianceState.RUNNING

        sm.update(BELOW_IDLE, _t(60))
        assert sm.state is ApplianceState.PAUSED

        sm.update(BELOW_IDLE, _t(60 + IDLE_TIMEOUT_SECS + 1))
        assert sm.state is ApplianceState.FINISHED

        sm.update(ABOVE_START, _t(200))
        assert sm.state is ApplianceState.RUNNING
        assert sm.cycle_duration_seconds == 0.0

    def test_cycle_duration_wall_clock_across_pause_and_resume(
        self, sm: ApplianceStateMachine
    ) -> None:
        """cycle_duration_seconds is wall-clock from start, not net motor-on time."""
        sm.update(ABOVE_START, _t(0))  # cycle_start = 0
        sm.update(ABOVE_START, _t(20))  # 20 s
        sm.update(BELOW_IDLE, _t(30))  # → PAUSED at t=30
        sm.update(ABOVE_START, _t(50))  # resume after 20 s paused
        sm.update(ABOVE_START, _t(65))  # 15 more s running
        assert sm.cycle_duration_seconds == pytest.approx(65.0)
