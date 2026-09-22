"""Deal with Cast discovery."""

from functools import partial
import logging
import threading
from typing import TYPE_CHECKING, override
from uuid import UUID

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.dispatcher import dispatcher_send
import pychromecast.discovery
import pychromecast.models

from .const import (
    CONF_KNOWN_HOSTS,
    INTERNAL_DISCOVERY_RUNNING_KEY,
    SIGNAL_CAST_DISCOVERED,
    SIGNAL_CAST_REMOVED,
)
from .helpers import ChromecastInfo, ChromeCastZeroconf

if TYPE_CHECKING:
    from . import CastConfigEntry

_LOGGER = logging.getLogger(__name__)


def discover_chromecast(
    hass: HomeAssistant,
    cast_info: pychromecast.models.CastInfo,
    config_entry: CastConfigEntry,
) -> None:
    """Discover a Chromecast."""

    info = ChromecastInfo(
        cast_info=cast_info,
    )

    if info.uuid is None:
        _LOGGER.error("Discovered chromecast without uuid %s", info)
        return

    info = info.fill_out_missing_chromecast_info(hass, config_entry)
    _LOGGER.debug("Discovered new or updated chromecast %s", info)

    if (ledger := config_entry.runtime_data.ledger) is not None:
        hass.loop.call_soon_threadsafe(
            partial(
                ledger.async_update_identity,
                info.uuid,
                name=info.friendly_name,
                host=info.cast_info.host,
                port=info.cast_info.port,
                seen=True,
            )
        )

    dispatcher_send(hass, SIGNAL_CAST_DISCOVERED, info)


def _remove_chromecast(hass: HomeAssistant, info: ChromecastInfo) -> None:
    # Removed chromecast
    _LOGGER.debug("Removed chromecast %s", info)

    dispatcher_send(hass, SIGNAL_CAST_REMOVED, info)


def setup_internal_discovery(
    hass: HomeAssistant, config_entry: CastConfigEntry
) -> None:
    """Set up the pychromecast internal discovery."""
    if INTERNAL_DISCOVERY_RUNNING_KEY not in hass.data:
        hass.data[INTERNAL_DISCOVERY_RUNNING_KEY] = threading.Lock()

    if not hass.data[INTERNAL_DISCOVERY_RUNNING_KEY].acquire(blocking=False):
        # Internal discovery is already running
        return

    class CastListener(pychromecast.discovery.AbstractCastListener):
        """Listener for discovering chromecasts."""

        @override
        def add_cast(self, uuid: UUID, _: str) -> None:
            """Handle zeroconf discovery of a new chromecast."""
            discover_chromecast(hass, browser.devices[uuid], config_entry)

        @override
        def update_cast(self, uuid: UUID, _: str) -> None:
            """Handle zeroconf discovery of an updated chromecast."""
            discover_chromecast(hass, browser.devices[uuid], config_entry)

        @override
        def remove_cast(
            self, uuid: UUID, service: str, cast_info: pychromecast.models.CastInfo
        ) -> None:
            """Handle zeroconf discovery of a removed chromecast."""
            _remove_chromecast(
                hass,
                ChromecastInfo(
                    cast_info=cast_info,
                ),
            )

    _LOGGER.debug("Starting internal pychromecast discovery")
    browser = pychromecast.discovery.CastBrowser(
        CastListener(),
        ChromeCastZeroconf.get_zeroconf(),
        config_entry.data.get(CONF_KNOWN_HOSTS),
    )
    config_entry.runtime_data.browser = browser
    browser.start_discovery()

    def stop_discovery(event: Event | None) -> None:
        """Stop discovery of new chromecasts."""
        _LOGGER.debug("Stopping internal pychromecast discovery")
        browser.stop_discovery()
        hass.data[INTERNAL_DISCOVERY_RUNNING_KEY].release()
        config_entry.runtime_data.browser = None
        config_entry.runtime_data.unsub_discovery_stop = None

    config_entry.runtime_data.unsub_discovery_stop = hass.bus.listen_once(
        EVENT_HOMEASSISTANT_STOP, stop_discovery
    )

    config_entry.add_update_listener(config_entry_updated)


def stop_internal_discovery(hass: HomeAssistant, config_entry: CastConfigEntry) -> None:
    """Stop the internal discovery started for this entry, if it is running."""
    runtime_data = config_entry.runtime_data
    if runtime_data.browser is None:
        return
    if (unsub := runtime_data.unsub_discovery_stop) is not None:
        unsub()
        runtime_data.unsub_discovery_stop = None
    _LOGGER.debug("Stopping internal pychromecast discovery (entry unload)")
    runtime_data.browser.stop_discovery()
    runtime_data.browser = None
    hass.data[INTERNAL_DISCOVERY_RUNNING_KEY].release()


async def config_entry_updated(
    hass: HomeAssistant, config_entry: CastConfigEntry
) -> None:
    """Handle config entry being updated."""
    if browser := config_entry.runtime_data.browser:
        browser.host_browser.update_hosts(config_entry.data.get(CONF_KNOWN_HOSTS))
