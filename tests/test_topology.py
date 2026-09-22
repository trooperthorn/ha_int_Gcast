"""Tests for group leadership and subnet awareness (WP3)."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
import pychromecast
from pychromecast.const import CAST_TYPE_GROUP
import pytest

from custom_components.cast.const import DOMAIN
from custom_components.cast.helpers import ChromecastInfo
from custom_components.cast.topology import TopologyTracker, _as_ipv4
from tests.test_media_player import (
    FakeGroupUUID,
    FakeUUID,
    FakeUUID2,
    async_setup_media_player_cast,
    get_fake_chromecast_info,
)

LEADER = "sensor.dos_leader"


def _group_info(host: str, port: int = 32046, dynamic: bool = False) -> ChromecastInfo:
    return ChromecastInfo(
        cast_info=pychromecast.models.CastInfo(
            services={pychromecast.discovery.HostServiceInfo(host, port)},
            uuid=FakeGroupUUID,
            model_name="Google Cast Group",
            friendly_name="Dos",
            host=host,
            port=port,
            cast_type=CAST_TYPE_GROUP,
            manufacturer="Google Inc.",
        ),
        is_dynamic_group=dynamic,
    )


@pytest.mark.usefixtures("mock_network")
async def test_group_leader_sensor_and_subnets(
    hass: HomeAssistant, mz_mock, caplog: pytest.LogCaptureFixture
) -> None:
    """The leader sensor reports the advertised leader and subnet placement."""
    await async_process_ha_core_config(hass, {"internal_url": "http://10.10.10.10:8123"})
    member_a = get_fake_chromecast_info(host="10.10.10.20", uuid=FakeUUID)
    member_b = get_fake_chromecast_info(host="10.10.30.5", uuid=FakeUUID2)
    mz_mock.get_multizone_memberships.side_effect = lambda uuid: (
        [str(FakeGroupUUID)] if uuid in (FakeUUID, FakeUUID2) else []
    )

    _, discover = await async_setup_media_player_cast(hass, member_a, wanted_uuids=[])
    discover("service-b", member_b)
    discover("service-group", _group_info("10.10.10.20"))
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    topology: TopologyTracker = entry.runtime_data.topology
    await topology.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(LEADER)
    assert state is not None
    assert state.state == "10.10.10.20"
    assert state.attributes["leader_uuid"] == str(FakeUUID)
    assert state.attributes["advertised_port"] == 32046
    assert state.attributes["is_dynamic_group"] is False
    assert set(state.attributes["member_uuids"]) == {str(FakeUUID), str(FakeUUID2)}
    assert state.attributes["members_span_subnets"] is True
    assert state.attributes["subnets"]["leader"] == "10.10.10.0/24"
    assert state.attributes["subnets"][str(FakeUUID2)] == "10.10.30.0/24"

    ledger = entry.runtime_data.ledger
    assert ledger.device(FakeUUID).subnet_mismatch is False
    assert ledger.device(FakeUUID2).subnet_mismatch is True
    outcome = hass.states.get("sensor.speaker_tts_outcome")
    assert outcome.attributes["subnet_mismatch"] is False
    assert topology.multihomed is False
    assert topology.internal_url_automatic is False
    assert "subnet_mismatch=True device_ip=10.10.30.5" in caplog.text

    # Leader migration: the group record moves to the other member's address.
    discover("service-group", _group_info("10.10.30.5", port=41000))
    await hass.async_block_till_done()
    await topology.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(LEADER)
    assert state.state == "10.10.30.5"
    assert state.attributes["leader_uuid"] == str(FakeUUID2)
    assert state.attributes["advertised_port"] == 41000
    assert state.attributes["members_span_subnets"] is True
    assert "leader moved from 10.10.10.20:32046 to 10.10.30.5:41000" in caplog.text

    diag = topology.as_dict()
    assert diag["home_networks"] == ["10.10.10.0/24"]
    assert diag["groups"][0]["name"] == "Dos"


@pytest.mark.usefixtures("mock_network")
async def test_single_subnet_group_does_not_span(
    hass: HomeAssistant, mz_mock, get_multizone_status_mock
) -> None:
    """A group whose members share the leader's subnet reports no span."""
    await async_process_ha_core_config(hass, {"internal_url": "http://10.10.10.10:8123"})
    member_a = get_fake_chromecast_info(host="10.10.10.20", uuid=FakeUUID)
    member_b = get_fake_chromecast_info(host="10.10.10.21", uuid=FakeUUID2)
    mz_mock.get_multizone_memberships.side_effect = lambda uuid: [str(FakeGroupUUID)]
    get_multizone_status_mock.return_value.dynamic_groups = [MagicMock(uuid=FakeGroupUUID)]
    _, discover = await async_setup_media_player_cast(hass, member_a, wanted_uuids=[])
    discover("service-b", member_b)
    discover("service-group", _group_info("10.10.10.21", dynamic=True))
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await entry.runtime_data.topology.async_refresh()
    await hass.async_block_till_done()

    # Dynamic groups have no entity; they are visible through the tracker only.
    assert hass.states.get(LEADER) is None
    group = entry.runtime_data.topology.groups[FakeGroupUUID]
    assert group.is_dynamic_group is True
    assert group.leader_uuid == FakeUUID2
    assert group.members_span_subnets is False


async def test_unknown_placement_without_ip_internal_url(hass: HomeAssistant) -> None:
    """A hostname internal_url leaves subnet placement unknown, never wrong."""
    await async_process_ha_core_config(
        hass, {"internal_url": "http://homeassistant.local:8123"}
    )
    member = get_fake_chromecast_info(host="10.10.10.20", uuid=FakeUUID)
    await async_setup_media_player_cast(hass, member)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    topology = entry.runtime_data.topology
    await topology.async_refresh()
    assert topology.internal_host == "homeassistant.local"
    assert topology.home_networks == []
    assert entry.runtime_data.ledger.device(FakeUUID).subnet_mismatch is None


async def test_assumed_prefix_when_no_adapter_matches(hass: HomeAssistant) -> None:
    """Without a matching adapter the host's /24 is assumed and logged."""
    await async_process_ha_core_config(hass, {"internal_url": "http://192.168.30.3:8123"})
    member = get_fake_chromecast_info(host="192.168.1.251", uuid=FakeUUID)
    await async_setup_media_player_cast(hass, member)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    topology = entry.runtime_data.topology
    await topology.async_refresh()
    assert [str(net) for net in topology.home_networks] == ["192.168.30.0/24"]
    assert entry.runtime_data.ledger.device(FakeUUID).subnet_mismatch is True


def test_as_ipv4() -> None:
    """Only IPv4 literals resolve; hostnames and IPv6 do not."""
    assert str(_as_ipv4("192.168.1.1")) == "192.168.1.1"
    assert _as_ipv4("fd14::1") is None
    assert _as_ipv4("speaker.local") is None
    assert _as_ipv4(None) is None


async def test_memberships_missing_device_is_tolerated(
    hass: HomeAssistant, mz_mock
) -> None:
    """A device unknown to the multizone manager does not break the refresh."""
    await async_process_ha_core_config(hass, {"internal_url": "http://10.10.10.10:8123"})
    member = get_fake_chromecast_info(host="10.10.10.20", uuid=FakeUUID)
    mz_mock.get_multizone_memberships.side_effect = KeyError(str(FakeUUID))
    _, discover = await async_setup_media_player_cast(hass, member, wanted_uuids=[])
    discover("service-group", _group_info("10.10.10.20"))
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await entry.runtime_data.topology.async_refresh()
    group = entry.runtime_data.topology.groups[FakeGroupUUID]
    assert group.member_uuids == []
    assert group.members_span_subnets is False
    assert isinstance(entry.runtime_data.multizone_manager, MagicMock)
