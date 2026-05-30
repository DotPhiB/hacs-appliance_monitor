"""Constants for appliance_monitor."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "appliance_monitor"

CONF_POWER_SENSOR = "power_sensor"
CONF_START_THRESHOLD = "start_threshold"
CONF_IDLE_THRESHOLD = "idle_threshold"
CONF_IDLE_TIMEOUT = "idle_timeout"
CONF_START_DELAY = "start_delay"

DEFAULT_START_THRESHOLD: int = 10
DEFAULT_IDLE_THRESHOLD: int = 3
DEFAULT_IDLE_TIMEOUT: int = 30
DEFAULT_START_DELAY: int = 0
