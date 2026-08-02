"""Constants for appliance_monitor."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "appliance_monitor"

CONF_POWER_SENSOR = "power_sensor"
CONF_START_THRESHOLD = "start_threshold"
CONF_START_DELAY = "start_delay"
CONF_FINISHED_WINDOW = "finished_window"
CONF_FINISHED_ENERGY_THRESHOLD = "finished_energy_threshold"
CONF_POST_CYCLE_ENABLED = "post_cycle_enabled"
CONF_POST_CYCLE_WINDOW = "post_cycle_window"
CONF_POST_CYCLE_ENERGY_THRESHOLD = "post_cycle_energy_threshold"

# Superseded by the window/energy pair above; still read when migrating v1 entries.
CONF_IDLE_THRESHOLD = "idle_threshold"
CONF_IDLE_TIMEOUT = "idle_timeout"

DEFAULT_START_THRESHOLD: int = 10
DEFAULT_START_DELAY: int = 0
# 5 min is the shortest window that separates a washing machine's mid-cycle soak
# phases from a genuinely finished cycle; see README for the measured bands.
DEFAULT_FINISHED_WINDOW: int = 300
DEFAULT_FINISHED_ENERGY_THRESHOLD: float = 0.3
DEFAULT_POST_CYCLE_ENABLED: bool = False
DEFAULT_POST_CYCLE_WINDOW: int = 300
DEFAULT_POST_CYCLE_ENERGY_THRESHOLD: float = 2.7

DEFAULT_IDLE_THRESHOLD: int = 3
DEFAULT_IDLE_TIMEOUT: int = 30
