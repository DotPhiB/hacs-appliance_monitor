"""ApplianceMonitorEntity base class."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ApplianceMonitorCoordinator


class ApplianceMonitorEntity(CoordinatorEntity[ApplianceMonitorCoordinator]):
    """Base entity for all Appliance Monitor entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ApplianceMonitorCoordinator) -> None:
        """Initialise the entity with device info derived from the config entry."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.domain,
                    coordinator.config_entry.entry_id,
                ),
            },
            name=coordinator.config_entry.title,
        )
