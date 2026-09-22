"""Consts for Cast integration."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, NotRequired, TypedDict
from uuid import UUID

from homeassistant.util.signal_type import SignalType

if TYPE_CHECKING:
    from .helpers import ChromecastInfo


DOMAIN = "cast"

# Stores a threading.Lock that is held by the internal pychromecast discovery.
INTERNAL_DISCOVERY_RUNNING_KEY = "cast_discovery_running"

# Dispatcher signal fired with a ChromecastInfo every time we discover a new
# Chromecast or receive it through configuration
SIGNAL_CAST_DISCOVERED: SignalType[ChromecastInfo] = SignalType("cast_discovered")

# Dispatcher signal fired with a ChromecastInfo every time a Chromecast is
# removed
SIGNAL_CAST_REMOVED: SignalType[ChromecastInfo] = SignalType("cast_removed")

# Dispatcher signal fired when a Chromecast should show a Home Assistant Cast view.
SIGNAL_HASS_CAST_SHOW_VIEW: SignalType[
    HomeAssistantControllerData, str, str, str | None
] = SignalType("cast_show_view")

CONF_IGNORE_CEC = "ignore_cec"
CONF_KNOWN_HOSTS = "known_hosts"


class HomeAssistantControllerData(TypedDict):
    """Data for creating a HomeAssistantController."""

    hass_url: str
    hass_uuid: str
    client_id: str | None
    refresh_token: str
    app_id: NotRequired[str]


# Fork additions; see DESIGN.md.
EVENT_DELIVERY_RESULT = "cast_delivery_result"
SIGNAL_HEALTH_UPDATED: SignalType[UUID] = SignalType("cast_health_updated")
SIGNAL_TOPOLOGY_UPDATED: SignalType[UUID] = SignalType("cast_topology_updated")

CONF_PROBE_ENABLED = "probe_enabled"
CONF_PROBE_INTERVAL = "probe_interval"
CONF_GROUP_PROBE_ENABLED = "group_probe_enabled"
CONF_PROBE_VIDEO_DEVICES = "probe_video_devices"
# Per-device base URL overrides: {"<uuid>": "http://host:port"}; see urls.py.
CONF_URL_OVERRIDES = "url_overrides"
DEFAULT_PROBE_ENABLED = True
DEFAULT_GROUP_PROBE_ENABLED = True
DEFAULT_PROBE_VIDEO_DEVICES = False
DEFAULT_PROBE_INTERVAL = 300
MIN_PROBE_INTERVAL = 60

# The default for every Delivery health option, in one place because two
# readers have to agree on it: the options flow, which shows the user what is
# in effect, and probe_options(), which decides what actually runs. When the
# flow filtered these to the keys already stored and the coordinator fell back
# to the defaults, an entry with no options saved drew every box unchecked
# while probing ran.
HEALTH_DEFAULTS: Mapping[str, bool | int] = MappingProxyType(
    {
        CONF_PROBE_ENABLED: DEFAULT_PROBE_ENABLED,
        CONF_PROBE_INTERVAL: DEFAULT_PROBE_INTERVAL,
        CONF_GROUP_PROBE_ENABLED: DEFAULT_GROUP_PROBE_ENABLED,
        CONF_PROBE_VIDEO_DEVICES: DEFAULT_PROBE_VIDEO_DEVICES,
    }
)

DELIVERY_TIMEOUT = 30.0
REQUEST_WATCHDOG = 45.0
PROBE_WATCHDOG = 20.0
CIRCUIT_BREAKER_TIMEOUTS = 2
CIRCUIT_BREAKER_MAX_BACKOFF = 3600
LEDGER_SIZE = 50
STALE_DEVICE_DAYS = 7
