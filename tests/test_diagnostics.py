"""Tests for the config-entry diagnostics download."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from custom_components.appliance_monitor.const import CONF_POWER_SENSOR
from custom_components.appliance_monitor.diagnostics import (
    async_get_config_entry_diagnostics,
)

POWER_SENSOR = "sensor.fake_power"


def _diagnostics(*, version: int = 2, minor_version: int = 1) -> dict:
    """Run the diagnostics dump against a mocked entry at the given schema."""
    entry = MagicMock()
    entry.version = version
    entry.minor_version = minor_version
    entry.data = {CONF_POWER_SENSOR: POWER_SENSOR}
    entry.options = {}
    entry.runtime_data.coordinator.data = {"state": "idle"}
    entry.runtime_data.coordinator.last_update_success = True

    hass = MagicMock()
    hass.states.get.return_value = None
    return asyncio.run(async_get_config_entry_diagnostics(hass, entry))


def test_reports_the_entry_schema_version() -> None:
    """
    A report has to say which schema the entry is on.

    With the v1 to v2 migration shipping, "migrated or created fresh" is the
    first thing worth knowing from a bug report.
    """
    config_entry = _diagnostics(version=2, minor_version=1)["config_entry"]
    assert config_entry["version"] == 2
    assert config_entry["minor_version"] == 1


def test_reports_an_unmigrated_entry() -> None:
    """An entry still on v1 reports v1, rather than the current schema."""
    assert _diagnostics(version=1)["config_entry"]["version"] == 1
