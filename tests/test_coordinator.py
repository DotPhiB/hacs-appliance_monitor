"""Tests for ApplianceMonitorCoordinator — disconnect routing and snapshot roundtrip."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.appliance_monitor.const import CONF_POWER_SENSOR
from custom_components.appliance_monitor.coordinator import ApplianceMonitorCoordinator
from custom_components.appliance_monitor.state_machine import (
    ApplianceState,
    ApplianceStateMachine,
)

POWER_SENSOR = "sensor.fake_power"

START_THRESHOLD = 10.0
FINISHED_WINDOW = 300.0
FINISHED_ENERGY_WH = 0.3


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
    )
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
