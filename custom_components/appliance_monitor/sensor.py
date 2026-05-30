"""Sensor platform for appliance_monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime

from .entity import ApplianceMonitorEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ApplianceMonitorCoordinator
    from .data import ApplianceMonitorConfigEntry

ENTITY_DESCRIPTIONS = (
    SensorEntityDescription(
        key="state",
        name="State",
        icon="mdi:washing-machine",
    ),
    SensorEntityDescription(
        key="cycle_count",
        name="Cycle Count",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cycle_start",
        name="Cycle Start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="cycle_duration",
        name="Cycle Duration",
        icon="mdi:timer",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="total_operating_time",
        name="Total Operating Time",
        icon="mdi:timer-cog",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ApplianceMonitorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_entities(
        ApplianceMonitorSensor(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class ApplianceMonitorSensor(ApplianceMonitorEntity, SensorEntity):
    """Appliance Monitor sensor."""

    def __init__(
        self,
        coordinator: ApplianceMonitorCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    @property
    def native_value(self) -> str | float | None:
        """Return the current sensor value."""
        return self.coordinator.data.get(self.entity_description.key)  # type: ignore[return-value]
