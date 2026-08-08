"""Diagnostics for Appliance Monitor — downloaded as JSON from the config-entry UI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import CONF_POWER_SENSOR

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import ApplianceMonitorConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ApplianceMonitorConfigEntry,
) -> dict[str, Any]:
    """Return diagnostic data for a config entry."""
    coordinator = entry.runtime_data.coordinator
    source_entity_id = entry.data.get(CONF_POWER_SENSOR)
    source_state = hass.states.get(source_entity_id) if source_entity_id else None

    return {
        "config_entry": {
            # Which schema the entry is on, so a report says whether it was
            # migrated or created fresh.
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "source_sensor": {
            "entity_id": source_entity_id,
            "state": source_state.state if source_state else None,
            "attributes": dict(source_state.attributes) if source_state else None,
        },
        "coordinator_data": coordinator.data,
        "last_update_success": coordinator.last_update_success,
    }
