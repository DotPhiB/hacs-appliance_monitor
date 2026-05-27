"""
Custom integration to integrate appliance_monitor with Home Assistant.

For more details about this integration, please refer to
https://github.com/dotphib/appliance_monitor
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .coordinator import ApplianceMonitorCoordinator
from .data import ApplianceMonitorData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

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

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ApplianceMonitorConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: ApplianceMonitorConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
