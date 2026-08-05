"""Sensor platform for appliance_monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)

from .const import (
    TUNING_FINISHED,
    TUNING_FIXED_WINDOWS,
    TUNING_KEY_PREFIX,
    TUNING_POST_CYCLE,
)
from .entity import ApplianceMonitorEntity
from .state_machine import ApplianceState

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ApplianceMonitorCoordinator
    from .data import ApplianceMonitorConfigEntry

ENTITY_DESCRIPTIONS = (
    SensorEntityDescription(
        key="state",
        translation_key="state",
        icon="mdi:washing-machine",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in ApplianceState],
    ),
    SensorEntityDescription(
        key="cycle_count",
        translation_key="cycle_count",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="cycle_start",
        translation_key="cycle_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="cycle_duration",
        translation_key="cycle_duration",
        icon="mdi:timer",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cycle_energy",
        translation_key="cycle_energy",
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="total_operating_time",
        translation_key="total_operating_time",
        icon="mdi:timer-cog",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="total_energy",
        translation_key="total_energy",
        icon="mdi:lightning-bolt-circle",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _tuning_description(key_suffix: str) -> SensorEntityDescription:
    """Build the description for one tuning sensor."""
    return SensorEntityDescription(
        key=f"{TUNING_KEY_PREFIX}{key_suffix}",
        translation_key=f"{TUNING_KEY_PREFIX}{key_suffix}",
        icon="mdi:chart-bell-curve-cumulative",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )


# Average power over a set of windows, reported on every reading whatever the
# appliance is doing. Off by default: they exist to be switched on for a cycle or
# two while picking windows and thresholds, then switched off again.
TUNING_ENTITY_DESCRIPTIONS = (
    *(_tuning_description(name) for name, _ in TUNING_FIXED_WINDOWS),
    _tuning_description(TUNING_FINISHED),
    _tuning_description(TUNING_POST_CYCLE),
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
        for entity_description in (*ENTITY_DESCRIPTIONS, *TUNING_ENTITY_DESCRIPTIONS)
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
    def native_value(self) -> str | float | datetime | None:
        """Return the current sensor value."""
        return self.coordinator.data.get(self.entity_description.key)  # type: ignore[return-value]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return this sensor's attributes, for the sensors that publish any."""
        attributes = self.coordinator.data.get("attributes", {})
        return attributes.get(self.entity_description.key)
