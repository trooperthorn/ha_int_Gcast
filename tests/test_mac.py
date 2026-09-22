"""Tests for resolving a cast device's hardware address."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from custom_components.cast.mac import async_resolve_mac


def _service_info(ip: str, mac: str) -> DhcpServiceInfo:
    return DhcpServiceInfo(ip=ip, hostname="speaker", macaddress=mac)


async def test_resolves_and_formats_known_host(hass: HomeAssistant) -> None:
    """A host the dhcp integration has seen resolves to a formatted MAC."""
    hass.config.components.add("dhcp")
    with patch(
        "homeassistant.components.dhcp.async_discovered_service_info",
        return_value=[_service_info("192.168.1.251", "ccf411abf8eb")],
    ):
        assert async_resolve_mac(hass, "192.168.1.251") == "cc:f4:11:ab:f8:eb"


async def test_unknown_host_returns_none(hass: HomeAssistant) -> None:
    """A speaker on a network dhcp never saw resolves to None."""
    hass.config.components.add("dhcp")
    with patch(
        "homeassistant.components.dhcp.async_discovered_service_info",
        return_value=[_service_info("192.168.1.251", "ccf411abf8eb")],
    ):
        assert async_resolve_mac(hass, "192.168.30.10") is None


async def test_returns_none_without_dhcp(hass: HomeAssistant) -> None:
    """dhcp is an after_dependency, so its absence must not raise."""
    assert "dhcp" not in hass.config.components
    assert async_resolve_mac(hass, "192.168.1.251") is None


async def test_returns_none_without_host(hass: HomeAssistant) -> None:
    """A cast device discovered without a host has no address to match."""
    hass.config.components.add("dhcp")
    assert async_resolve_mac(hass, None) is None
