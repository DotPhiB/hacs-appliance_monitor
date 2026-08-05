"""Tests for async_migrate_entry — the v1 idle pair becoming the v2 window pair."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from custom_components.appliance_monitor import async_migrate_entry
from custom_components.appliance_monitor.const import (
    CONF_FINISHED_POWER_THRESHOLD,
    CONF_FINISHED_WINDOW,
    CONF_IDLE_THRESHOLD,
    CONF_IDLE_TIMEOUT,
    CONF_POWER_SENSOR,
    CONF_START_THRESHOLD,
    DEFAULT_IDLE_THRESHOLD,
    DEFAULT_IDLE_TIMEOUT,
)

POWER_SENSOR = "sensor.fake_power"

# Deliberately not the defaults: a migration that rescaled or resampled the
# numbers would still look right against 3 W / 30 s.
IDLE_THRESHOLD = 5
IDLE_TIMEOUT = 120


def _entry(
    *,
    version: int = 1,
    data: dict | None = None,
    options: dict | None = None,
) -> MagicMock:
    """Build a mock config entry at *version* carrying *data* and *options*."""
    entry = MagicMock()
    entry.version = version
    entry.data = {} if data is None else data
    entry.options = {} if options is None else options
    entry.title = "Washing machine"
    return entry


def _migrate(entry: MagicMock) -> tuple[bool, MagicMock]:
    """Run the migration against a mocked hass; return its result and that hass."""
    hass = MagicMock()
    result = asyncio.run(async_migrate_entry(hass, entry))
    return result, hass


def _written(hass: MagicMock) -> dict:
    """Return the kwargs the migration passed to async_update_entry."""
    return hass.config_entries.async_update_entry.call_args.kwargs


def test_v1_pair_carries_over_unchanged() -> None:
    """
    Threshold and timeout become the power/window pair with no arithmetic.

    Both sides are watts and seconds respectively, and what the appliance drew
    between two readings is unknowable, so any rescaling would invent data.
    """
    entry = _entry(
        data={
            CONF_POWER_SENSOR: POWER_SENSOR,
            CONF_IDLE_THRESHOLD: IDLE_THRESHOLD,
            CONF_IDLE_TIMEOUT: IDLE_TIMEOUT,
        },
    )
    result, hass = _migrate(entry)
    written = _written(hass)

    assert result is True
    assert written["version"] == 2
    assert written["data"][CONF_FINISHED_POWER_THRESHOLD] == IDLE_THRESHOLD
    assert written["data"][CONF_FINISHED_WINDOW] == IDLE_TIMEOUT


def test_legacy_keys_do_not_survive() -> None:
    """The old keys are removed, so nothing can read them back by accident."""
    entry = _entry(
        data={CONF_IDLE_THRESHOLD: IDLE_THRESHOLD, CONF_IDLE_TIMEOUT: IDLE_TIMEOUT},
    )
    _, hass = _migrate(entry)

    assert CONF_IDLE_THRESHOLD not in _written(hass)["data"]
    assert CONF_IDLE_TIMEOUT not in _written(hass)["data"]


def test_unrelated_settings_are_preserved() -> None:
    """Migration touches the idle pair only; the rest of the entry is untouched."""
    entry = _entry(
        data={
            CONF_POWER_SENSOR: POWER_SENSOR,
            CONF_START_THRESHOLD: 42,
            CONF_IDLE_THRESHOLD: IDLE_THRESHOLD,
            CONF_IDLE_TIMEOUT: IDLE_TIMEOUT,
        },
    )
    _, hass = _migrate(entry)
    written = _written(hass)["data"]

    assert written[CONF_POWER_SENSOR] == POWER_SENSOR
    assert written[CONF_START_THRESHOLD] == 42


def test_options_are_migrated_as_well_as_data() -> None:
    """
    Values the user changed later live in options and must migrate too.

    Options win over data at read time, so an unmigrated options dict would
    leave the entry running on the defaults.
    """
    entry = _entry(
        data={CONF_POWER_SENSOR: POWER_SENSOR},
        options={CONF_IDLE_THRESHOLD: IDLE_THRESHOLD, CONF_IDLE_TIMEOUT: IDLE_TIMEOUT},
    )
    _, hass = _migrate(entry)
    written = _written(hass)

    assert written["options"][CONF_FINISHED_POWER_THRESHOLD] == IDLE_THRESHOLD
    assert written["options"][CONF_FINISHED_WINDOW] == IDLE_TIMEOUT
    # Data had neither key, so it gains neither.
    assert CONF_FINISHED_WINDOW not in written["data"]


def test_zero_timeout_becomes_a_zero_window() -> None:
    """
    A timeout of 0 is a real setting, not a missing one.

    It asks for the check to be taken on each reading as it arrives, so it must
    survive as a window of 0 rather than falling back to the default.
    """
    entry = _entry(
        data={CONF_IDLE_THRESHOLD: IDLE_THRESHOLD, CONF_IDLE_TIMEOUT: 0},
    )
    _, hass = _migrate(entry)

    assert _written(hass)["data"][CONF_FINISHED_WINDOW] == 0


def test_half_migrated_entry_falls_back_to_defaults() -> None:
    """One key present is enough to migrate; the absent one takes its default."""
    entry = _entry(data={CONF_IDLE_TIMEOUT: IDLE_TIMEOUT})
    _, hass = _migrate(entry)
    written = _written(hass)["data"]

    assert written[CONF_FINISHED_WINDOW] == IDLE_TIMEOUT
    assert written[CONF_FINISHED_POWER_THRESHOLD] == DEFAULT_IDLE_THRESHOLD

    entry = _entry(data={CONF_IDLE_THRESHOLD: IDLE_THRESHOLD})
    _, hass = _migrate(entry)
    written = _written(hass)["data"]

    assert written[CONF_FINISHED_POWER_THRESHOLD] == IDLE_THRESHOLD
    assert written[CONF_FINISHED_WINDOW] == DEFAULT_IDLE_TIMEOUT


def test_entry_without_the_idle_pair_is_only_versioned() -> None:
    """
    No keys to migrate means no keys invented — just the version bump.

    Writing the defaults in explicitly would pin the entry to today's values
    and stop it following any later change to them.
    """
    entry = _entry(data={CONF_POWER_SENSOR: POWER_SENSOR})
    result, hass = _migrate(entry)
    written = _written(hass)

    assert result is True
    assert written["version"] == 2
    assert written["data"] == {CONF_POWER_SENSOR: POWER_SENSOR}
    assert CONF_FINISHED_WINDOW not in written["data"]
    assert CONF_FINISHED_POWER_THRESHOLD not in written["data"]


def test_v2_entry_is_left_alone() -> None:
    """An entry already on the current version is not rewritten."""
    entry = _entry(version=2, data={CONF_FINISHED_WINDOW: 300})
    result, hass = _migrate(entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_not_called()


def test_future_version_is_left_alone() -> None:
    """A downgrade must not push a newer entry back through this migration."""
    entry = _entry(version=3, data={CONF_FINISHED_WINDOW: 300})
    result, hass = _migrate(entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_not_called()
