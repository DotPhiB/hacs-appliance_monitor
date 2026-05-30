"""Button platform for appliance_monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory

from .entity import ApplianceMonitorEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ApplianceMonitorCoordinator
    from .data import ApplianceMonitorConfigEntry

_BUTTONS: tuple[tuple[ButtonEntityDescription, str], ...] = (
    (
        ButtonEntityDescription(
            key="reset_state",
            translation_key="reset_state",
            icon="mdi:restart",
            entity_category=EntityCategory.CONFIG,
        ),
        "reset",
    ),
    (
        ButtonEntityDescription(
            key="reset_cycle_count",
            translation_key="reset_cycle_count",
            icon="mdi:counter",
            entity_category=EntityCategory.CONFIG,
        ),
        "reset_cycle_count",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ApplianceMonitorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        ApplianceMonitorButton(
            coordinator=coordinator,
            entity_description=description,
            action=getattr(coordinator, action_name),
        )
        for description, action_name in _BUTTONS
    )


class ApplianceMonitorButton(ApplianceMonitorEntity, ButtonEntity):
    """A button that triggers a single coordinator action."""

    def __init__(
        self,
        coordinator: ApplianceMonitorCoordinator,
        entity_description: ButtonEntityDescription,
        action: Callable[[], None],
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )
        self._action = action

    async def async_press(self) -> None:
        """Handle button press."""
        self._action()
