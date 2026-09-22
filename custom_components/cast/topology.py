"""Group leadership and subnet awareness (WP3).

Facts: a speaker group advertises its `_googlecast._tcp` record on the
leader's IP with a dynamic high port instead of 8009, and the device setup
endpoint reports nothing useful about multizone on current firmware
(RESEARCH.md, WP3). Membership comes from pychromecast's MultizoneManager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Network, ip_address
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from uuid import UUID

from homeassistant.components import network
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import SIGNAL_HEALTH_UPDATED, SIGNAL_TOPOLOGY_UPDATED
from .helpers import ChromecastInfo

if TYPE_CHECKING:
    from . import CastConfigEntry

_LOGGER = logging.getLogger(__name__)

ASSUMED_PREFIX = 24


@dataclass(slots=True)
class GroupTopology:
    """What is known about one speaker group."""

    uuid: UUID
    name: str | None
    leader_ip: str | None
    advertised_port: int | None
    is_dynamic_group: bool
    leader_uuid: UUID | None = None
    member_uuids: list[UUID] = field(default_factory=list)
    member_ips: dict[str, str | None] = field(default_factory=dict)
    subnets: dict[str, str | None] = field(default_factory=dict)
    members_span_subnets: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for diagnostics and sensor attributes."""
        return {
            "uuid": str(self.uuid),
            "name": self.name,
            "leader_ip": self.leader_ip,
            "advertised_port": self.advertised_port,
            "is_dynamic_group": self.is_dynamic_group,
            "leader_uuid": str(self.leader_uuid) if self.leader_uuid else None,
            "member_uuids": [str(uuid) for uuid in self.member_uuids],
            "member_ips": self.member_ips,
            "subnets": self.subnets,
            "members_span_subnets": self.members_span_subnets,
        }


@dataclass
class TopologyTracker:
    """Track group leaders, members, and subnet placement for an entry."""

    hass: HomeAssistant
    entry: CastConfigEntry
    infos: dict[UUID, ChromecastInfo] = field(default_factory=dict)
    groups: dict[UUID, GroupTopology] = field(default_factory=dict)
    home_networks: list[IPv4Network] = field(default_factory=list)
    adapter_networks: list[IPv4Network] = field(default_factory=list)
    internal_host: str | None = None
    internal_url_automatic: bool | None = None
    multihomed: bool | None = None

    @callback
    def async_record_discovery(self, info: ChromecastInfo) -> None:
        """Remember the latest discovery record for a device or group."""
        previous = self.infos.get(info.uuid)
        self.infos[info.uuid] = info
        if (
            previous is not None
            and info.is_audio_group
            and (
                previous.cast_info.host != info.cast_info.host
                or previous.cast_info.port != info.cast_info.port
            )
        ):
            _LOGGER.info(
                "[group %s uuid=%s] leader moved from %s:%s to %s:%s",
                info.friendly_name,
                info.uuid,
                previous.cast_info.host,
                previous.cast_info.port,
                info.cast_info.host,
                info.cast_info.port,
            )

    async def async_refresh(self) -> None:
        """Recompute networks, subnet placement, and group topology."""
        await self._async_load_networks()
        self._compute_groups()
        self._apply_subnet_mismatch()
        for uuid in self.groups:
            async_dispatcher_send(self.hass, SIGNAL_TOPOLOGY_UPDATED, uuid)

    async def _async_load_networks(self) -> None:
        try:
            adapters = await network.async_get_adapters(self.hass)
        except Exception as err:
            _LOGGER.debug("adapter enumeration failed: %s", err)
            adapters = []
        self.adapter_networks = [
            IPv4Network(f"{ipv4['address']}/{ipv4['network_prefix']}", strict=False)
            for adapter in adapters
            if adapter["enabled"]
            for ipv4 in adapter["ipv4"]
        ]
        enabled_with_ipv4 = [
            adapter for adapter in adapters if adapter["enabled"] and adapter["ipv4"]
        ]
        self.multihomed = len(enabled_with_ipv4) >= 2 if adapters else None
        self.internal_url_automatic = self.hass.config.internal_url is None

        self.internal_host = None
        self.home_networks = []
        try:
            url = get_url(self.hass, allow_external=False)
        except NoURLAvailableError:
            return
        self.internal_host = urlparse(url).hostname
        host_ip = _as_ipv4(self.internal_host)
        if host_ip is None:
            _LOGGER.debug(
                "internal_url host %s is not an IPv4 address; subnet placement is "
                "unknown until it is pinned to an address",
                self.internal_host,
            )
            return
        self.home_networks = [net for net in self.adapter_networks if host_ip in net]
        if not self.home_networks:
            self.home_networks = [IPv4Network(f"{host_ip}/{ASSUMED_PREFIX}", strict=False)]
            _LOGGER.debug(
                "internal_url host %s matches no adapter; assuming /%d",
                host_ip,
                ASSUMED_PREFIX,
            )

    def _subnet_of(self, host: str | None) -> str | None:
        ip = _as_ipv4(host)
        if ip is None:
            return None
        for net in self.adapter_networks:
            if ip in net:
                return str(net)
        return str(IPv4Network(f"{ip}/{ASSUMED_PREFIX}", strict=False))

    def _compute_groups(self) -> None:
        mz_mgr = self.entry.runtime_data.multizone_manager
        members_by_group: dict[str, list[UUID]] = {}
        if mz_mgr is not None:
            for uuid, info in self.infos.items():
                if info.is_audio_group:
                    continue
                try:
                    memberships = mz_mgr.get_multizone_memberships(uuid)
                except KeyError:
                    continue
                for group_uuid in memberships:
                    members_by_group.setdefault(group_uuid, []).append(uuid)

        hosts_to_uuid = {
            info.cast_info.host: uuid
            for uuid, info in self.infos.items()
            if not info.is_audio_group and info.cast_info.host
        }
        groups: dict[UUID, GroupTopology] = {}
        for uuid, info in self.infos.items():
            if not info.is_audio_group:
                continue
            leader_ip = info.cast_info.host or None
            topology = GroupTopology(
                uuid=uuid,
                name=info.friendly_name,
                leader_ip=leader_ip,
                advertised_port=info.cast_info.port,
                is_dynamic_group=bool(info.is_dynamic_group),
                leader_uuid=hosts_to_uuid.get(leader_ip) if leader_ip else None,
                member_uuids=sorted(members_by_group.get(str(uuid), []), key=str),
            )
            topology.member_ips = {
                str(member): (self.infos[member].cast_info.host if member in self.infos else None)
                for member in topology.member_uuids
            }
            subnets: dict[str, str | None] = {"leader": self._subnet_of(leader_ip)}
            for member, host in topology.member_ips.items():
                subnets[member] = self._subnet_of(host)
            topology.subnets = subnets
            known = {net for net in subnets.values() if net is not None}
            topology.members_span_subnets = len(known) > 1 if known else None
            groups[uuid] = topology
            _LOGGER.debug(
                "[group %s uuid=%s] leader_ip=%s port=%s leader_uuid=%s members=%s "
                "subnets=%s span=%s dynamic=%s",
                topology.name,
                uuid,
                leader_ip,
                topology.advertised_port,
                topology.leader_uuid,
                [str(member) for member in topology.member_uuids],
                subnets,
                topology.members_span_subnets,
                topology.is_dynamic_group,
            )
        self.groups = groups

    def _apply_subnet_mismatch(self) -> None:
        ledger = self.entry.runtime_data.ledger
        if ledger is None:
            return
        for uuid, info in self.infos.items():
            ip = _as_ipv4(info.cast_info.host)
            if ip is None or not self.home_networks:
                mismatch: bool | None = None
            else:
                mismatch = not any(ip in net for net in self.home_networks)
            health = ledger.device(uuid)
            if health.subnet_mismatch == mismatch:
                continue
            _LOGGER.debug(
                "[%s %s uuid=%s] subnet_mismatch=%s device_ip=%s home_networks=%s",
                health.entity_id,
                health.name,
                uuid,
                mismatch,
                ip,
                [str(net) for net in self.home_networks],
            )
            health.subnet_mismatch = mismatch
            async_dispatcher_send(self.hass, SIGNAL_HEALTH_UPDATED, uuid)

    def as_dict(self) -> dict[str, Any]:
        """Serialize for diagnostics."""
        return {
            "internal_host": self.internal_host,
            "internal_url_automatic": self.internal_url_automatic,
            "multihomed": self.multihomed,
            "adapter_networks": [str(net) for net in self.adapter_networks],
            "home_networks": [str(net) for net in self.home_networks],
            "groups": [group.as_dict() for group in self.groups.values()],
        }


def _as_ipv4(host: str | None) -> IPv4Address | None:
    if not host:
        return None
    try:
        ip = ip_address(host)
    except ValueError:
        return None
    return ip if isinstance(ip, IPv4Address) else None
