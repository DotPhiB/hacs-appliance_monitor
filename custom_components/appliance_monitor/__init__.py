"""
Custom integration to integrate appliance_monitor with Home Assistant.

For more details about this integration, please refer to
https://github.com/dotphib/appliance_monitor
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_FINISHED_POWER_THRESHOLD,
    CONF_FINISHED_WINDOW,
    CONF_IDLE_THRESHOLD,
    CONF_IDLE_TIMEOUT,
    CONF_POWER_SENSOR,
    DEFAULT_IDLE_THRESHOLD,
    DEFAULT_IDLE_TIMEOUT,
    DOMAIN,
    LOGGER,
)
from .coordinator import STORAGE_VERSION, ApplianceMonitorCoordinator
from .data import ApplianceMonitorData

if TYPE_CHECKING:
    from homeassistant.core import Event, EventStateChangedData, HomeAssistant

    from .data import ApplianceMonitorConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: ApplianceMonitorConfigEntry,
) -> bool:
    """Migrate a v1 entry (idle threshold + timeout) to the window/power pair."""
    if entry.version >= 2:  # noqa: PLR2004
        return True

    def _migrate(values: dict) -> dict:
        if CONF_IDLE_THRESHOLD not in values and CONF_IDLE_TIMEOUT not in values:
            return values
        migrated = dict(values)
        # v1 asked for power to stay below a threshold for a timeout; v2 asks
        # for the average across a window to be below it. Not the same test —
        # a blip reset v1's timer where v2 absorbs it — but both sides are
        # watts, and the readings between two samples are unknowable, so
        # carrying the numbers over unchanged is the only mapping that does not
        # invent a consumption profile. It errs towards the more forgiving
        # behaviour, which is the point of the change.
        migrated[CONF_FINISHED_POWER_THRESHOLD] = migrated.pop(
            CONF_IDLE_THRESHOLD, DEFAULT_IDLE_THRESHOLD
        )
        migrated[CONF_FINISHED_WINDOW] = migrated.pop(
            CONF_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT
        )
        return migrated

    hass.config_entries.async_update_entry(
        entry,
        data=_migrate(dict(entry.data)),
        options=_migrate(dict(entry.options)),
        version=2,
    )
    LOGGER.info("Migrated %s to windowed average-power detection", entry.title)
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApplianceMonitorConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    coordinator = ApplianceMonitorCoordinator(hass=hass, config_entry=entry)
    entry.runtime_data = ApplianceMonitorData(coordinator=coordinator)

    await coordinator.async_load_persisted_snapshot()
    await coordinator.async_config_entry_first_refresh()

    async def _handle_power_change(
        event: Event[EventStateChangedData],
    ) -> None:
        """Trigger a coordinator refresh when the source sensor reports a new value."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if (
            new_state is not None
            and old_state is not None
            and new_state.state == old_state.state
        ):
            return
        await coordinator.async_source_changed()

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            entry.data[CONF_POWER_SENSOR],
            _handle_power_change,
        ),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ApplianceMonitorConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant,
    entry: ApplianceMonitorConfigEntry,
) -> None:
    """Delete persisted totals when the integration entry is removed."""
    store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    await store.async_remove()


async def async_reload_entry(
    hass: HomeAssistant,
    entry: ApplianceMonitorConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
