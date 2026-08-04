"""Tests for ApplianceMonitorCoordinator — disconnect routing and snapshot roundtrip."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.appliance_monitor.const import (
    CONF_FINISHED_WINDOW,
    CONF_POWER_SENSOR,
    TRIGGER_COMMAND,
    TRIGGER_POLL,
    TRIGGER_SOURCE_UPDATE,
    TUNING_FINISHED,
    TUNING_FIXED_WINDOWS,
    TUNING_KEY_PREFIX,
    TUNING_POST_CYCLE,
)
from custom_components.appliance_monitor.coordinator import ApplianceMonitorCoordinator
from custom_components.appliance_monitor.state_machine import (
    ApplianceState,
    ApplianceStateMachine,
)

POWER_SENSOR = "sensor.fake_power"

START_THRESHOLD = 10.0
FINISHED_WINDOW = 300.0
FINISHED_ENERGY_WH = 0.3
FINISHED_WINDOW_TICKS = int(FINISHED_WINDOW) + 10


def _make_coordinator() -> ApplianceMonitorCoordinator:
    """Build a coordinator with the heavy HA base-class init bypassed."""
    coordinator = ApplianceMonitorCoordinator.__new__(ApplianceMonitorCoordinator)
    coordinator.hass = MagicMock()
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.data = {CONF_POWER_SENSOR: POWER_SENSOR}
    coordinator.config_entry.options = {}
    coordinator._state_machine = ApplianceStateMachine(
        start_threshold=START_THRESHOLD,
        finished_window_seconds=FINISHED_WINDOW,
        finished_energy_threshold_wh=FINISHED_ENERGY_WH,
        observed_windows_seconds=[width for _, width in TUNING_FIXED_WINDOWS],
    )
    coordinator._pending_trigger = TRIGGER_POLL
    coordinator._trigger = TRIGGER_POLL
    coordinator._store = MagicMock()
    coordinator._store.async_load = AsyncMock(return_value=None)
    coordinator._store.async_save = AsyncMock()
    coordinator._store.async_delay_save = MagicMock()
    coordinator.data = None
    # Stub DataUpdateCoordinator internals not initialised because we
    # bypassed super().__init__ via __new__.
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


def _set_source_state(coordinator: ApplianceMonitorCoordinator, value: str) -> None:
    """Configure the mocked HA state machine to return *value* for our source."""
    state = MagicMock()
    state.state = value
    coordinator.hass.states.get = MagicMock(return_value=state)


def _update(coordinator: ApplianceMonitorCoordinator) -> dict:
    """Run one coordinator refresh synchronously."""
    return asyncio.run(coordinator._async_update_data())


def test_unavailable_source_marks_disconnected() -> None:
    """`unavailable` source → state machine becomes DISCONNECTED, no exception."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "unavailable")
    data = _update(coordinator)
    assert data["state"] == ApplianceState.DISCONNECTED.value
    assert coordinator._state_machine.state is ApplianceState.DISCONNECTED


def test_unknown_source_marks_disconnected() -> None:
    """`unknown` source → DISCONNECTED (same as unavailable)."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "unknown")
    data = _update(coordinator)
    assert data["state"] == ApplianceState.DISCONNECTED.value


def test_missing_source_marks_disconnected() -> None:
    """Source entity not present in HA → DISCONNECTED."""
    coordinator = _make_coordinator()
    coordinator.hass.states.get = MagicMock(return_value=None)
    data = _update(coordinator)
    assert data["state"] == ApplianceState.DISCONNECTED.value


def test_non_numeric_source_marks_disconnected() -> None:
    """Non-numeric source value (e.g. 'off') → DISCONNECTED, no exception."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "off")
    data = _update(coordinator)
    assert data["state"] == ApplianceState.DISCONNECTED.value


def test_numeric_source_drives_state_machine() -> None:
    """Numeric source value advances the state machine."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    data = _update(coordinator)
    # 50 W is above start_threshold and start_delay defaults to 0 → RUNNING.
    assert data["state"] == ApplianceState.RUNNING.value
    assert data["power"] == pytest.approx(50.0)


def test_reconnect_restores_prior_state() -> None:
    """After mark_disconnected, the next numeric sample resumes the prior state."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    _update(coordinator)  # drive to RUNNING
    _set_source_state(coordinator, "unavailable")
    _update(coordinator)  # disconnect
    assert coordinator._state_machine.state is ApplianceState.DISCONNECTED
    _set_source_state(coordinator, "50.0")
    data = _update(coordinator)  # reconnect
    assert data["state"] == ApplianceState.RUNNING.value


def test_finished_transition_persists_immediately() -> None:
    """A FINISHED transition writes the snapshot now, not via the 10 s debounce."""
    coordinator = _make_coordinator()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)

    def at(offset_seconds: float) -> datetime:
        return t0 + timedelta(seconds=offset_seconds)

    with patch(
        "custom_components.appliance_monitor.coordinator.utcnow",
    ) as mock_utcnow:
        mock_utcnow.return_value = at(0)
        _set_source_state(coordinator, "50.0")
        _update(coordinator)  # → RUNNING (no FINISHED, debounced save)

        _set_source_state(coordinator, "0.0")
        elapsed = 10.0
        while elapsed < FINISHED_WINDOW:
            mock_utcnow.return_value = at(elapsed)
            _update(coordinator)  # quiet, but the window is not covered yet
            elapsed += 10.0

        # Sanity: no immediate save up to this point.
        assert coordinator._store.async_save.call_count == 0

        mock_utcnow.return_value = at(FINISHED_WINDOW)
        _update(coordinator)  # first fully covered window → FINISHED

    assert coordinator._state_machine.state is ApplianceState.FINISHED
    assert coordinator._store.async_save.call_count == 1
    saved = coordinator._store.async_save.call_args.args[0]
    assert saved["state"] == ApplianceState.FINISHED.value
    assert saved["cycle_count"] == 1


def test_reset_persists_immediately() -> None:
    """Reset button writes the snapshot immediately."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    _update(coordinator)  # → RUNNING
    asyncio.run(coordinator.reset())
    coordinator._store.async_save.assert_called_once()


def test_reset_cycle_count_persists_immediately() -> None:
    """Reset-cycle-count button writes the snapshot immediately."""
    coordinator = _make_coordinator()
    asyncio.run(coordinator.reset_cycle_count())
    coordinator._store.async_save.assert_called_once()


def test_unloaded_persists_immediately() -> None:
    """Unloaded button writes the snapshot immediately."""
    coordinator = _make_coordinator()
    asyncio.run(coordinator.unloaded())
    coordinator._store.async_save.assert_called_once()


def test_unloaded_does_not_stop_a_running_cycle() -> None:
    """Pressing Unloaded mid-cycle leaves the appliance RUNNING."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    _update(coordinator)  # → RUNNING
    asyncio.run(coordinator.unloaded())
    assert coordinator._state_machine.state is ApplianceState.RUNNING


def test_tuning_sensors_report_every_window() -> None:
    """Every fixed and configured window shows up in the coordinator data."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    data = _update(coordinator)
    expected = {f"{TUNING_KEY_PREFIX}{name}" for name, _ in TUNING_FIXED_WINDOWS}
    expected |= {
        f"{TUNING_KEY_PREFIX}{TUNING_FINISHED}",
        f"{TUNING_KEY_PREFIX}{TUNING_POST_CYCLE}",
    }
    assert expected <= set(data)


def test_tuning_sensors_report_outside_a_cycle() -> None:
    """Measuring does not depend on the appliance running or the phase existing."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "0.5")  # below start threshold: stays IDLE
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    key = f"{TUNING_KEY_PREFIX}30s"
    with patch(
        "custom_components.appliance_monitor.coordinator.utcnow",
    ) as mock_utcnow:
        for offset in range(0, 40, 10):
            mock_utcnow.return_value = t0 + timedelta(seconds=offset)
            data = _update(coordinator)
    assert coordinator._state_machine.state is ApplianceState.IDLE
    assert data[key] == pytest.approx(0.5 * 30 / 3600, rel=1e-3)


def test_tuning_window_not_yet_covered_is_none() -> None:
    """A window without a full span of readings reports nothing, not zero."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    data = _update(coordinator)
    assert data[f"{TUNING_KEY_PREFIX}10m"] is None


def test_tuning_attributes_describe_the_window() -> None:
    """Fixed windows carry their length, sample count and refresh trigger."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    data = _update(coordinator)
    attrs = data["attributes"][f"{TUNING_KEY_PREFIX}30s"]
    assert attrs["window_seconds"] == 30
    assert attrs["trigger"] == TRIGGER_POLL
    assert "threshold" not in attrs
    assert "headroom_ratio" not in attrs


def test_source_samples_exclude_the_poll() -> None:
    """A poll-only refresh contributes nothing to the source sample count."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    key = f"{TUNING_KEY_PREFIX}30s"
    with patch(
        "custom_components.appliance_monitor.coordinator.utcnow",
    ) as mock_utcnow:
        for offset in range(0, 60, 10):
            mock_utcnow.return_value = t0 + timedelta(seconds=offset)
            data = _update(coordinator)  # poll-driven throughout
    assert data["attributes"][key]["source_samples_in_window"] == 0

    with patch(
        "custom_components.appliance_monitor.coordinator.utcnow",
    ) as mock_utcnow:
        mock_utcnow.return_value = t0 + timedelta(seconds=60)
        coordinator._pending_trigger = TRIGGER_SOURCE_UPDATE
        data = _update(coordinator)
    assert data["attributes"][key]["source_samples_in_window"] == 1


def test_headroom_ratio_locates_the_threshold() -> None:
    """The configured windows report where they sit relative to their threshold."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "3600.0")  # 1 Wh per second
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    with patch(
        "custom_components.appliance_monitor.coordinator.utcnow",
    ) as mock_utcnow:
        for offset in range(0, FINISHED_WINDOW_TICKS, 10):
            mock_utcnow.return_value = t0 + timedelta(seconds=offset)
            data = _update(coordinator)
    attrs = data["attributes"][f"{TUNING_KEY_PREFIX}{TUNING_FINISHED}"]
    # 3600 W across the 300 s window is 300 Wh against a 0.3 Wh threshold.
    expected = 300.0 / FINISHED_ENERGY_WH
    assert attrs["headroom_ratio"] == pytest.approx(expected, rel=1e-3)
    assert attrs["headroom_ratio"] > 1  # still far above: nowhere near finished


def test_average_power_normalises_the_window() -> None:
    """Every window reports the same rate under steady draw, whatever its length."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "3600.0")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    with patch(
        "custom_components.appliance_monitor.coordinator.utcnow",
    ) as mock_utcnow:
        for offset in range(0, 620, 10):
            mock_utcnow.return_value = t0 + timedelta(seconds=offset)
            data = _update(coordinator)
    rates = [
        data["attributes"][f"{TUNING_KEY_PREFIX}{name}"]["average_power_w"]
        for name, _ in TUNING_FIXED_WINDOWS
    ]
    # The Wh figures differ 20-fold across these windows; the rate does not.
    for rate in rates:
        assert rate == pytest.approx(3600.0, rel=1e-3)


def test_headroom_ratio_is_none_without_a_verdict() -> None:
    """No measurement yet means no ratio, rather than a misleading zero."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    data = _update(coordinator)  # single sample: window not covered
    attrs = data["attributes"][f"{TUNING_KEY_PREFIX}{TUNING_FINISHED}"]
    assert attrs["headroom_ratio"] is None


def test_configured_window_attributes_carry_the_threshold() -> None:
    """The configured windows also publish what they are judged against."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    data = _update(coordinator)
    attrs = data["attributes"][f"{TUNING_KEY_PREFIX}{TUNING_FINISHED}"]
    assert attrs["window_seconds"] == FINISHED_WINDOW
    assert attrs["threshold"] == pytest.approx(FINISHED_ENERGY_WH)
    assert attrs["threshold_unit"] == "Wh"


def test_zero_window_reports_no_energy_figure() -> None:
    """A degenerate window is judged on live power, so there is no Wh to plot."""
    coordinator = _make_coordinator()
    coordinator.config_entry.options = {CONF_FINISHED_WINDOW: 0}
    _set_source_state(coordinator, "50.0")
    data = _update(coordinator)
    key = f"{TUNING_KEY_PREFIX}{TUNING_FINISHED}"
    # Measuring a zero-length span would yield a constant, meaningless 0.0 Wh.
    assert data[key] is None
    attrs = data["attributes"][key]
    assert attrs["window_seconds"] == 0
    assert attrs["measures"] == "power"
    assert attrs["threshold_unit"] == "W"


def test_trigger_distinguishes_source_updates_from_polls() -> None:
    """A source-driven refresh is labelled differently from the 10 s poll."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    key = f"{TUNING_KEY_PREFIX}30s"

    coordinator.async_refresh = AsyncMock()
    asyncio.run(coordinator.async_source_changed())
    assert coordinator._pending_trigger == TRIGGER_SOURCE_UPDATE
    data = _update(coordinator)
    assert data["attributes"][key]["trigger"] == TRIGGER_SOURCE_UPDATE

    # The flag is consumed, so the next refresh is a plain poll again.
    data = _update(coordinator)
    assert data["attributes"][key]["trigger"] == TRIGGER_POLL


def test_trigger_marks_button_driven_updates() -> None:
    """A button press republishes data without a new reading behind it."""
    coordinator = _make_coordinator()
    _set_source_state(coordinator, "50.0")
    _update(coordinator)
    asyncio.run(coordinator.unloaded())
    data = coordinator.async_set_updated_data.call_args.args[0]
    assert data["attributes"][f"{TUNING_KEY_PREFIX}30s"]["trigger"] == TRIGGER_COMMAND


def test_snapshot_roundtrip_preserves_state_before_disconnect() -> None:
    """state_before_disconnect persists across an HA-restart-shaped roundtrip."""
    src = _make_coordinator()
    _set_source_state(src, "50.0")
    _update(src)  # RUNNING
    _set_source_state(src, "unavailable")
    _update(src)  # DISCONNECTED, prior = RUNNING

    snapshot = src._snapshot_for_persist()
    assert snapshot["state"] == ApplianceState.DISCONNECTED.value
    assert snapshot["state_before_disconnect"] == ApplianceState.RUNNING.value

    # Fresh coordinator loads the snapshot as if HA had restarted mid-disconnect.
    dst = _make_coordinator()
    dst._store.async_load = AsyncMock(return_value=snapshot)
    asyncio.run(dst.async_load_persisted_snapshot())
    assert dst._state_machine.state is ApplianceState.DISCONNECTED
    assert dst._state_machine.state_before_disconnect is ApplianceState.RUNNING

    # Source returns: state must resume RUNNING, not the IDLE default.
    _set_source_state(dst, "50.0")
    data = _update(dst)
    assert data["state"] == ApplianceState.RUNNING.value
