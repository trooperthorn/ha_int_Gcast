"""Tests for the diagnostics download (WP4)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import device_registry as dr
import pytest

from custom_components.cast.const import DOMAIN
from custom_components.cast.diagnostics import async_get_config_entry_diagnostics
from tests.test_health import _play, _setup, _status
from tests.test_media_player import FakeUUID


@pytest.mark.usefixtures("mock_network")
async def test_diagnostics_answer_is_tts_working(
    hass: HomeAssistant, device_registry: dr.DeviceRegistry
) -> None:
    """One download names the URLs, every device's outcome, the ledger, and orphans."""
    _, media_status_cb = await _setup(hass)
    await async_process_ha_core_config(
        hass,
        {"internal_url": "http://10.10.10.10:8123", "external_url": "https://secret.example.org"},
    )
    await _play(hass)
    media_status_cb(_status(player_state="IDLE", idle_reason="ERROR", player_is_idle=True))
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    ghost = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "deadbeefdeadbeefdeadbeefdeadbeef")},
        name="Ghost mini",
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["urls"]["internal_url"] == "http://10.10.10.10:8123"
    assert diag["urls"]["internal_url_pinned"] is True
    assert diag["urls"]["internal_url_adapter"] == "10.10.10.0/24"
    assert diag["urls"]["external_url"] == "**REDACTED**"
    assert diag["urls"]["external_host"] == "**REDACTED**"
    assert diag["entry"]["data"]["user_id"] == "**REDACTED**"

    (device,) = diag["devices"]
    assert device["uuid"] == str(FakeUUID)
    assert device["entity_id"] == "media_player.speaker"
    assert device["host"] == "192.168.178.42"
    assert device["last_outcome"] == "fetch_failed"
    assert device["last_success"] is None
    assert device["subnet_mismatch"] is True
    assert device["model"] == "Chromecast"
    # dhcp is not set up in this test, so the address is simply not known
    assert device["mac"] is None

    assert diag["ledger"][-1]["outcome"] == "fetch_failed"
    assert diag["ledger"][-1]["url_source"] is None
    assert diag["groups"] == []
    assert diag["network"]["home_networks"] == ["10.10.10.0/24"]
    assert diag["registry_without_discovery"] == [
        {
            "device_id": ghost.id,
            "name": "Ghost mini",
            "identifiers": ["cast:deadbeefdeadbeefdeadbeefdeadbeef"],
            "disabled": False,
        }
    ]
    assert diag["probe"]["options"]["interval"] == 300
    assert diag["repairs"]["active_issues"] == []
    assert diag["repairs"]["consecutive_fetch_failures"][str(FakeUUID)] == 1
