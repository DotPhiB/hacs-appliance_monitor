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

from .const import CONF_POWER_SENSOR, DOMAIN
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
        await coordinator.async_refresh()

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
