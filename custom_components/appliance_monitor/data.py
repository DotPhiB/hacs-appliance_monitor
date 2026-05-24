"""Custom types for appliance_monitor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .coordinator import ApplianceMonitorCoordinator


type ApplianceMonitorConfigEntry = ConfigEntry[ApplianceMonitorData]


@dataclass
class ApplianceMonitorData:
    """Runtime data for the Appliance Monitor integration."""

    coordinator: ApplianceMonitorCoordinator
    integration: Integration
