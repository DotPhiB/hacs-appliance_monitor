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

    def test_transitions_to_running_at_threshold(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Power exactly at start_threshold triggers IDLE→RUNNING (inclusive)."""
        sm.update(START_THRESHOLD, _t(0))
        assert sm.state is ApplianceState.RUNNING

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
        """No operating time is accumulated on the first update regardless of timestamp."""
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

    def test_stays_running_during_brief_dip(
        self, sm: ApplianceStateMachine
    ) -> None:
        """A power dip below idle for less than idle_timeout keeps state RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS))  # exactly at the boundary
        assert sm.state is ApplianceState.RUNNING

    def test_transitions_to_finished_after_idle_timeout(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Power below idle for longer than idle_timeout → FINISHED."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        assert sm.state is ApplianceState.FINISHED

    def test_recovery_during_idle_countdown_keeps_running(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Power returning above idle during the countdown resets the timer."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(ABOVE_START, _t(10 + IDLE_TIMEOUT_SECS / 2))  # recovers mid-countdown
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS / 2 + 1))  # dips again
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS / 2 + IDLE_TIMEOUT_SECS))
        # Countdown restarted on the second dip; not yet expired.
        assert sm.state is ApplianceState.RUNNING

    def test_cycle_duration_accumulates(self, sm: ApplianceStateMachine) -> None:
        """cycle_duration_seconds grows by elapsed seconds while RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        assert sm.cycle_duration_seconds == pytest.approx(30.0)

    def test_cycle_duration_includes_low_draw_phase(
        self, sm: ApplianceStateMachine
    ) -> None:
        """cycle_duration_seconds keeps growing during low-draw phases (still RUNNING)."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS - 5))
        assert sm.state is ApplianceState.RUNNING
        assert sm.cycle_duration_seconds == pytest.approx(10 + IDLE_TIMEOUT_SECS - 5)


class TestFinishedTransitions:
    """Transitions out of FINISHED."""

    @pytest.fixture
    def finished_sm(self, sm: ApplianceStateMachine) -> ApplianceStateMachine:
        """Return a state machine in FINISHED state."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        return sm

    def test_starts_new_cycle_at_threshold(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """Power exactly at start_threshold starts a new cycle from FINISHED (inclusive)."""
        finished_sm.update(START_THRESHOLD, _t(200))
        assert finished_sm.state is ApplianceState.RUNNING

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
        delayed_sm.update(BELOW_IDLE, _t(self.START_DELAY - 1))
        delayed_sm.update(ABOVE_START, _t(self.START_DELAY))
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
        delayed_sm.update(ABOVE_START, _t(t_run + 200))
        assert delayed_sm.state is ApplianceState.FINISHED


class TestReset:
    """reset() forces the machine back to IDLE regardless of current state."""

    def test_reset_from_running(self, sm: ApplianceStateMachine) -> None:
        """Reset while RUNNING returns the machine to IDLE."""
        sm.update(ABOVE_START, _t(0))
        sm.reset()
        assert sm.state is ApplianceState.IDLE

    def test_reset_from_finished(self, sm: ApplianceStateMachine) -> None:
        """Reset while FINISHED returns the machine to IDLE."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
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

    def test_reset_preserves_cycle_count(self, sm: ApplianceStateMachine) -> None:
        """reset() does not zero the cycle counter."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
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

    def test_increments_across_multiple_cycles(
        self, sm: ApplianceStateMachine
    ) -> None:
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
        sm.reset_cycle_count()
        assert sm.cycle_count == 0

    def test_reset_cycle_count_leaves_state_intact(
        self, sm: ApplianceStateMachine
    ) -> None:
        """reset_cycle_count() does not affect the current machine state."""
        self._finish_cycle(sm)
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
    """total_operating_seconds accumulates RUNNING time and survives resets."""

    def test_accumulates_running_time(self, sm: ApplianceStateMachine) -> None:
        """Operating time grows while RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        assert sm.total_operating_seconds == pytest.approx(30.0)

    def test_accumulates_during_low_draw_phase(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Operating time grows even when power is low — state is still RUNNING."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        # 30 s of low-draw mid-cycle (still RUNNING, below idle_timeout):
        sm.update(BELOW_IDLE, _t(40))
        assert sm.state is ApplianceState.RUNNING
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
        sm.update(BELOW_IDLE, _t(0))
        sm.update(BELOW_IDLE, _t(3600))
        assert sm.cycle_energy_kwh == 0.0

    def test_total_energy_integrates_while_idle(
        self, sm: ApplianceStateMachine
    ) -> None:
        """total_energy_kwh accumulates standby consumption during IDLE."""
        sm.update(BELOW_IDLE, _t(0))
        sm.update(BELOW_IDLE, _t(3600))
        assert sm.total_energy_kwh == pytest.approx(BELOW_IDLE * 3600 / 3_600_000.0)

    def test_cycle_energy_frozen_while_finished(
        self, sm: ApplianceStateMachine
    ) -> None:
        """cycle_energy_kwh does not change while in FINISHED state."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        frozen = sm.cycle_energy_kwh
        sm.update(BELOW_IDLE, _t(1000))
        assert sm.cycle_energy_kwh == pytest.approx(frozen)

    def test_total_energy_integrates_while_finished(
        self, sm: ApplianceStateMachine
    ) -> None:
        """total_energy_kwh keeps accumulating residual draw after FINISHED."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(10))
        sm.update(BELOW_IDLE, _t(10 + IDLE_TIMEOUT_SECS + 1))
        total_at_finish = sm.total_energy_kwh
        sm.update(BELOW_IDLE, _t(1000))
        assert sm.total_energy_kwh > total_at_finish

    def test_cycle_energy_resets_on_new_cycle(
        self, sm: ApplianceStateMachine
    ) -> None:
        """cycle_energy_kwh zeroes when a new cycle starts."""
        sm.update(self.POWER_W, _t(0))
        sm.update(self.POWER_W, _t(60))
        sm.update(BELOW_IDLE, _t(70))
        sm.update(BELOW_IDLE, _t(70 + IDLE_TIMEOUT_SECS + 1))
        assert sm.cycle_energy_kwh > 0.0
        sm.update(self.POWER_W, _t(500))
        assert sm.cycle_energy_kwh == 0.0

    def test_total_energy_survives_new_cycle(
        self, sm: ApplianceStateMachine
    ) -> None:
        """total_energy_kwh accumulates across cycles, never resets."""
        sm.update(self.POWER_W, _t(0))
        sm.update(self.POWER_W, _t(60))
        sm.update(BELOW_IDLE, _t(70))
        sm.update(BELOW_IDLE, _t(70 + IDLE_TIMEOUT_SECS + 1))
        first_total = sm.total_energy_kwh
        sm.update(self.POWER_W, _t(500))
        sm.update(self.POWER_W, _t(560))
        assert sm.total_energy_kwh > first_total

    def test_cycle_energy_cleared_by_reset(self, sm: ApplianceStateMachine) -> None:
        """reset() zeroes cycle_energy."""
        sm.update(self.POWER_W, _t(0))
        sm.update(self.POWER_W, _t(60))
        sm.reset()
        assert sm.cycle_energy_kwh == 0.0

    def test_total_energy_survives_reset(self, sm: ApplianceStateMachine) -> None:
        """total_energy_kwh is preserved after reset()."""
        sm.update(self.POWER_W, _t(0))
        sm.update(self.POWER_W, _t(60))
        total_before = sm.total_energy_kwh
        sm.reset()
        assert sm.total_energy_kwh == pytest.approx(total_before)


class TestRestoreSnapshot:
    """restore_snapshot() rehydrates state and totals from persisted storage."""

    def test_defaults_when_nothing_provided(self, sm: ApplianceStateMachine) -> None:
        """restore_snapshot() with no args leaves the machine in pristine IDLE."""
        sm.restore_snapshot()
        assert sm.state is ApplianceState.IDLE
        assert sm.cycle_count == 0
        assert sm.cycle_start is None
        assert sm.cycle_duration_seconds == 0.0
        assert sm.cycle_energy_kwh == 0.0
        assert sm.total_operating_seconds == 0.0
        assert sm.total_energy_kwh == 0.0

    def test_restores_running_state(self, sm: ApplianceStateMachine) -> None:
        """Restoring state=RUNNING resumes the cycle so FINISHED detection works."""
        sm.restore_snapshot(
            state=ApplianceState.RUNNING,
            cycle_start=_t(0),
            cycle_duration_seconds=600.0,
            cycle_energy_kwh=0.5,
            cycle_count=3,
        )
        assert sm.state is ApplianceState.RUNNING
        assert sm.cycle_start == _t(0)
        assert sm.cycle_duration_seconds == 600.0
        assert sm.cycle_energy_kwh == 0.5

    def test_restored_running_can_reach_finished(
        self, sm: ApplianceStateMachine
    ) -> None:
        """After restoring RUNNING with a mid-cycle low draw, FINISHED still fires."""
        sm.restore_snapshot(
            state=ApplianceState.RUNNING,
            cycle_start=_t(0),
            cycle_duration_seconds=600.0,
            cycle_count=2,
        )
        # First tick: below idle. Sets _below_idle_since but no integration yet.
        sm.update(BELOW_IDLE, _t(10_000))
        # Second tick: still below idle, past timeout.
        sm.update(BELOW_IDLE, _t(10_000 + IDLE_TIMEOUT_SECS + 1))
        assert sm.state is ApplianceState.FINISHED
        assert sm.cycle_count == 3  # incremented on FINISHED

    def test_first_tick_after_restore_does_not_inflate_totals(
        self, sm: ApplianceStateMachine
    ) -> None:
        """First tick after restore skips integration — downtime gap not counted."""
        sm.restore_snapshot(
            state=ApplianceState.RUNNING,
            cycle_start=_t(0),
            total_operating_seconds=500.0,
            total_energy_kwh=1.0,
        )
        sm.update(ABOVE_START, _t(99_999))  # large gap; should NOT integrate
        assert sm.total_operating_seconds == 500.0
        assert sm.total_energy_kwh == 1.0


class TestFullCycle:
    """End-to-end scenarios covering the full state graph."""

    def test_complete_cycle(self, sm: ApplianceStateMachine) -> None:
        """Full cycle: IDLE→RUNNING→(low draw)→RUNNING→FINISHED→RUNNING."""
        sm.update(ABOVE_START, _t(0))
        assert sm.state is ApplianceState.RUNNING

        sm.update(BELOW_IDLE, _t(30))  # low draw mid-cycle — still RUNNING
        assert sm.state is ApplianceState.RUNNING

        sm.update(ABOVE_START, _t(45))  # back to high draw — still RUNNING
        assert sm.state is ApplianceState.RUNNING

        sm.update(BELOW_IDLE, _t(60))
        sm.update(BELOW_IDLE, _t(60 + IDLE_TIMEOUT_SECS + 1))
        assert sm.state is ApplianceState.FINISHED

        sm.update(ABOVE_START, _t(200))
        assert sm.state is ApplianceState.RUNNING
        assert sm.cycle_duration_seconds == 0.0

    def test_cycle_duration_wall_clock_through_low_draw(
        self, sm: ApplianceStateMachine
    ) -> None:
        """cycle_duration_seconds is wall-clock from start through low-draw phases."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(20))
        sm.update(BELOW_IDLE, _t(30))
        sm.update(ABOVE_START, _t(50))
        sm.update(ABOVE_START, _t(65))
        assert sm.cycle_duration_seconds == pytest.approx(65.0)
