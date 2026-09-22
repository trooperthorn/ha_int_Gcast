"""Tests for repair issues and stale device removal (WP4)."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from aiohttp.test_utils import TestClient
from homeassistant.components.repairs.websocket_api import (
    RepairsFlowIndexView,
    RepairsFlowResourceView,
)
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.cast.const import DOMAIN
from custom_components.cast.issues import (
    ISSUE_FETCH_FAILED,
    ISSUE_GROUP_SPANS,
    ISSUE_MULTIHOMED,
    ISSUE_STALE_DEVICE,
    RepairManager,
)
from tests.test_health import OUTCOME, _play, _setup, _status
from tests.test_media_player import (
    FakeGroupUUID,
    FakeUUID,
    FakeUUID2,
    get_fake_chromecast_info,
)
from tests.test_topology import _group_info, async_setup_media_player_cast


async def _start_fix(client: TestClient, issue_id: str) -> dict[str, Any]:
    resp = await client.post(RepairsFlowIndexView.url, json={"handler": DOMAIN, "issue_id": issue_id})
    assert resp.status == HTTPStatus.OK, await resp.text()
    return await resp.json()


async def _finish_fix(client: TestClient, flow_id: str) -> dict[str, Any]:
    resp = await client.post(RepairsFlowResourceView.url.format(flow_id=flow_id), json={})
    assert resp.status == HTTPStatus.OK, await resp.text()
    return await resp.json()


def _issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_fetch_failed_issue_raises_and_autoresolves(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Two consecutive fetch failures raise the issue; one success clears it."""
    _, media_status_cb = await _setup(hass)
    issue_id = f"{ISSUE_FETCH_FAILED}.{FakeUUID}"

    await _play(hass)
    media_status_cb(_status(player_state="IDLE", idle_reason="ERROR", player_is_idle=True))
    await hass.async_block_till_done()
    assert _issue(hass, issue_id) is None

    await _play(hass)
    media_status_cb(_status(player_state="IDLE", idle_reason="ERROR", player_is_idle=True))
    await hass.async_block_till_done()
    issue = _issue(hass, issue_id)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.translation_placeholders["name"] == "Speaker"
    assert issue.translation_placeholders["url_source"] == "internal_url"
    assert issue.translation_placeholders["count"] == "2"
    assert "repair issue raised id=tts_fetch_failed" in caplog.text

    await _play(hass)
    media_status_cb(_status(player_state="BUFFERING", media_session_id=9))
    await hass.async_block_till_done()
    assert _issue(hass, issue_id) is None
    assert "repair issue cleared id=tts_fetch_failed" in caplog.text
    assert hass.states.get(OUTCOME).state == "ok"


@pytest.mark.usefixtures("mock_network")
async def test_group_span_and_multihomed_issues(hass: HomeAssistant, mz_mock) -> None:
    """Subnet-spanning groups and an automatic internal URL on two adapters warn."""
    await async_process_ha_core_config(hass, {"internal_url": "http://10.10.10.10:8123"})
    member_a = get_fake_chromecast_info(host="10.10.10.20", uuid=FakeUUID)
    member_b = get_fake_chromecast_info(host="10.10.30.5", uuid=FakeUUID2)
    mz_mock.get_multizone_memberships.side_effect = lambda uuid: [str(FakeGroupUUID)]
    _, discover = await async_setup_media_player_cast(hass, member_a, wanted_uuids=[])
    discover("service-b", member_b)
    discover("service-group", _group_info("10.10.10.20"))
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    repairs: RepairManager = entry.runtime_data.repairs
    topology = entry.runtime_data.topology
    await topology.async_refresh()
    repairs.async_check_topology(topology)
    span_id = f"{ISSUE_GROUP_SPANS}.{FakeGroupUUID}"
    issue = _issue(hass, span_id)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["subnets"] == "10.10.10.0/24, 10.10.30.0/24"
    assert _issue(hass, ISSUE_MULTIHOMED) is None

    # Members move onto one subnet: the issue clears without dismissal.
    discover("service-b", get_fake_chromecast_info(host="10.10.10.21", uuid=FakeUUID2))
    await hass.async_block_till_done()
    await topology.async_refresh()
    repairs.async_check_topology(topology)
    assert _issue(hass, span_id) is None

    # Automatic internal URL with two adapters.
    topology.multihomed = True
    topology.internal_url_automatic = True
    repairs.async_check_topology(topology)
    assert _issue(hass, ISSUE_MULTIHOMED) is not None
    topology.internal_url_automatic = False
    repairs.async_check_topology(topology)
    assert _issue(hass, ISSUE_MULTIHOMED) is None


async def test_stale_device_issue_and_fix_flow(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    device_registry: dr.DeviceRegistry,
    hass_storage: dict[str, Any],
) -> None:
    """A registry device unseen for 7 days gets a fixable issue that removes it."""
    assert await async_setup_component(hass, "repairs", {})
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    repairs: RepairManager = entry.runtime_data.repairs
    ghost_uuid = uuid4()
    ghost = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, str(ghost_uuid).replace("-", ""))},
        name="Master Google mini (old)",
    )

    # First sighting of the registry entry: tracked, not yet stale.
    assert repairs.async_check_stale({FakeUUID}) == []
    issue_id = f"{ISSUE_STALE_DEVICE}.{ghost.id}"
    assert _issue(hass, issue_id) is None

    # Eight days later with no discovery: stale.
    repairs.tracked_since[str(ghost_uuid)] = dt_util.utcnow() - timedelta(days=8)
    candidates = repairs.async_check_stale({FakeUUID})
    assert [c.device_id for c in candidates] == [ghost.id]
    issue = _issue(hass, issue_id)
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_placeholders["name"] == "Master Google mini (old)"
    assert "never since" in issue.translation_placeholders["last_seen"]

    # Discovery seeing it again clears the issue.
    repairs.async_device_seen(ghost_uuid)
    assert _issue(hass, issue_id) is None
    assert device_registry.async_get(ghost.id) is not None

    # Stale again, and the fix flow removes the registry device.
    repairs.last_seen[str(ghost_uuid)] = dt_util.utcnow() - timedelta(days=9)
    repairs.async_check_stale({FakeUUID})
    assert _issue(hass, issue_id) is not None
    client = await hass_client()
    flow = await _start_fix(client, issue_id)
    assert flow["type"] == "form"
    assert flow["step_id"] == "confirm"
    assert flow["description_placeholders"]["name"] == "Master Google mini (old)"
    result = await _finish_fix(client, flow["flow_id"])
    assert result["type"] == "create_entry"
    assert device_registry.async_get(ghost.id) is None
    assert _issue(hass, issue_id) is None

    # The store persists what was seen.
    await repairs.async_flush()
    assert str(ghost_uuid) in hass_storage["cast.health"]["data"]["last_seen"]


async def test_repair_manager_load_restores_last_seen(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Persisted last_seen timestamps are restored into the ledger on setup."""
    stamp = "2026-09-20T10:00:00+00:00"
    hass_storage["cast.health"] = {
        "version": 1,
        "key": "cast.health",
        "data": {"last_seen": {str(FakeUUID): stamp, "not-a-uuid": stamp}, "tracked_since": {}},
    }
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    health = entry.runtime_data.ledger.device(FakeUUID)
    # Discovery during setup refreshed last_seen past the stored value.
    assert health.last_seen is not None
    assert health.last_seen >= dt_util.parse_datetime(stamp)
    diag = entry.runtime_data.repairs.as_dict()
    assert diag["active_issues"] == []
    assert isinstance(diag["consecutive_fetch_failures"], dict)


async def test_fix_flow_unknown_issue() -> None:
    """Only the stale device issue has a fix flow."""
    from custom_components.cast.repairs import async_create_fix_flow

    with pytest.raises(ValueError):
        await async_create_fix_flow(MagicMock(), "tts_fetch_failed.x", None)
