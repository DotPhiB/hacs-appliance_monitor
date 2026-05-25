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

    def test_initial_runtime_zero(self, sm: ApplianceStateMachine) -> None:
        """runtime_seconds is zero before any update."""
        assert sm.runtime_seconds == 0.0


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

    def test_runtime_zero_on_start(self, sm: ApplianceStateMachine) -> None:
        """Runtime is zero on IDLE→RUNNING transition (no prior time elapsed)."""
        sm.update(ABOVE_START, _t(30))
        assert sm.runtime_seconds == 0.0

    def test_first_update_never_accumulates_runtime(
        self, sm: ApplianceStateMachine
    ) -> None:
        """No runtime is accumulated on the first update regardless of timestamp."""
        sm.update(ABOVE_START, _t(9999))
        assert sm.runtime_seconds == 0.0


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

    def test_runtime_accumulates(self, sm: ApplianceStateMachine) -> None:
        """Runtime grows by elapsed seconds on each RUNNING update."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        assert sm.runtime_seconds == pytest.approx(30.0)

    def test_runtime_cumulative_across_updates(self, sm: ApplianceStateMachine) -> None:
        """Runtime sums elapsed time across multiple consecutive RUNNING updates."""
        sm.update(ABOVE_START, _t(0))
        sm.update(ABOVE_START, _t(30))
        sm.update(ABOVE_START, _t(50))
        assert sm.runtime_seconds == pytest.approx(50.0)

    def test_runtime_includes_interval_to_paused(
        self, sm: ApplianceStateMachine
    ) -> None:
        """Elapsed time up to the RUNNING→PAUSED transition is counted in runtime."""
        sm.update(ABOVE_START, _t(0))
        sm.update(BELOW_IDLE, _t(20))
        assert sm.runtime_seconds == pytest.approx(20.0)


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

    def test_runtime_not_accumulated_while_paused(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """Runtime does not grow during PAUSED state."""
        runtime_at_pause = paused_sm.runtime_seconds
        paused_sm.update(BELOW_IDLE, _t(10 + 30))
        assert paused_sm.runtime_seconds == pytest.approx(runtime_at_pause)

    def test_runtime_resumes_after_recovery(
        self, paused_sm: ApplianceStateMachine
    ) -> None:
        """Runtime accumulates again once the appliance resumes from PAUSED."""
        paused_sm.update(ABOVE_START, _t(20))  # resume
        paused_sm.update(ABOVE_START, _t(35))  # 15 s of running
        assert paused_sm.runtime_seconds == pytest.approx(10.0 + 15.0)


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

    def test_runtime_resets_on_new_cycle(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """Runtime is zeroed when FINISHED→RUNNING begins a new cycle."""
        finished_sm.update(ABOVE_START, _t(200))
        assert finished_sm.runtime_seconds == 0.0

    def test_pause_start_cleared_on_new_cycle(
        self, finished_sm: ApplianceStateMachine
    ) -> None:
        """_pause_start is cleared when a new cycle starts from FINISHED."""
        finished_sm.update(ABOVE_START, _t(200))
        assert finished_sm._pause_start is None


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

    def test_runtime_not_lost_during_pending_pause(
        self, delayed_sm: ApplianceStateMachine
    ) -> None:
        """Runtime keeps accumulating while the pause delay has not yet elapsed."""
        delayed_sm.update(ABOVE_START, _t(0))
        delayed_sm.update(ABOVE_START, _t(20))  # 20 s running
        delayed_sm.update(BELOW_IDLE, _t(30))  # dip — still RUNNING, 10 more s
        delayed_sm.update(BELOW_IDLE, _t(40))  # still within delay — 10 more s
        assert delayed_sm.state is ApplianceState.RUNNING
        assert delayed_sm.runtime_seconds == pytest.approx(40.0)


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
        assert sm.runtime_seconds == 0.0

    def test_runtime_across_pause_and_resume(self, sm: ApplianceStateMachine) -> None:
        """Runtime accumulates correctly across a RUNNING→PAUSED→RUNNING sequence."""
        sm.update(ABOVE_START, _t(0))  # start
        sm.update(ABOVE_START, _t(20))  # 20 s running
        sm.update(BELOW_IDLE, _t(30))  # pause at t=30 (10 more s running → 30 total)
        sm.update(ABOVE_START, _t(50))  # resume after 20 s paused
        sm.update(ABOVE_START, _t(65))  # 15 more s running
        assert sm.runtime_seconds == pytest.approx(30.0 + 15.0)
