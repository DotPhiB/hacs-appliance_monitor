"""Binary sensor platform for appliance_monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .entity import ApplianceMonitorEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ApplianceMonitorCoordinator
    from .data import ApplianceMonitorConfigEntry

ENTITY_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="running",
        name="Running",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    BinarySensorEntityDescription(
        key="finished",
        name="Finished",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ApplianceMonitorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary_sensor platform."""
    async_add_entities(
        ApplianceMonitorBinarySensor(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class ApplianceMonitorBinarySensor(ApplianceMonitorEntity, BinarySensorEntity):
    """Appliance Monitor binary sensor."""

    def __init__(
        self,
        coordinator: ApplianceMonitorCoordinator,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    @property
    def is_on(self) -> bool:
        """Return True when the sensor condition is active."""
        return bool(self.coordinator.data.get(self.entity_description.key))
