"""Resolve the hardware address of a cast device from its IP address.

pychromecast never reports a MAC: discovery is mDNS, and the TXT record
carries the UUID, model and friendly name but no hardware address. The
address has to come from something that has seen the device on the wire.

The dhcp integration keeps exactly that. It watches DHCP traffic and runs
aiodiscover against the networks Home Assistant is attached to, so every
host it has seen maps an IP to a MAC. Reading it costs nothing and needs no
extra connection to the speaker, which matters because a speaker on another
VLAN may not be reachable from Home Assistant on any port but 8009.

A MAC lets the device registry link this device to the one the UniFi
integration creates for the same client. Devices are not merged across
config entries since Home Assistant Core 2026.8, so the two remain separate
entries; they become linked, which is what list_linked_devices reports.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import format_mac

_LOGGER = logging.getLogger(__name__)


@callback
def async_resolve_mac(hass: HomeAssistant, host: str | None) -> str | None:
    """Return the formatted MAC for host, or None when it is not known.

    None is the normal answer for a speaker Home Assistant has never seen a
    lease or an ARP reply for, including one on a network it does not reach.
    The device is registered without a connection in that case.
    """
    if not host:
        return None

    # dhcp is an after_dependency: it is normally loaded, but a user can
    # exclude it, and it is absent in tests that do not ask for it.
    if "dhcp" not in hass.config.components:
        return None

    from homeassistant.components.dhcp import (
        async_discovered_service_info,
    )

    for service_info in async_discovered_service_info(hass):
        if service_info.ip == host:
            return format_mac(service_info.macaddress)

    _LOGGER.debug("No hardware address known for cast device at %s", host)
    return None
