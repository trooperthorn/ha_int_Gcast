"""Tests for per-device URL overrides."""

from __future__ import annotations

from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cast.const import DOMAIN
from custom_components.cast.health import DeliveryOutcome
from custom_components.cast.urls import (
    normalize_override,
    rewrite_hass_url,
    url_overrides,
)
from tests.test_coordinator import FakeTarget, _bare_coordinator, _wait_for
from tests.test_health import ENTITY_ID, OUTCOME, _play, _setup, _status
from tests.test_media_player import FakeUUID

OVERRIDE = "http://192.168.30.3:8123"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://192.168.30.3:8123", "http://192.168.30.3:8123"),
        (" https://ha.example/ ", "https://ha.example"),
        ("http://192.168.30.3:8123/api", None),
        ("192.168.30.3:8123", None),
        ("ftp://x", None),
        ("http://user@host", None),
        ("http://host?x=1", None),
        ("", None),
    ],
)
def test_normalize_override(raw: str, expected: str | None) -> None:
    """Only scheme, host, and port survive; anything else is rejected."""
    assert normalize_override(raw) == expected


async def test_url_overrides_skips_bad_entries(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Invalid keys and values are logged and ignored, valid ones kept."""
    good = uuid4()
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            "url_overrides": {
                str(good): "http://10.0.0.5:8123/",
                "not-a-uuid": "http://10.0.0.6:8123",
                str(uuid4()): "10.0.0.7",
            }
        },
    )
    assert url_overrides(entry) == {good: "http://10.0.0.5:8123"}
    assert "not a device uuid" in caplog.text
    assert "not a base URL" in caplog.text


async def test_rewrite_only_touches_own_urls(hass: HomeAssistant) -> None:
    """A Home Assistant URL is re-based; a third-party URL is returned unchanged."""
    await async_process_ha_core_config(
        hass, {"internal_url": "http://example.local:8123"}
    )
    assert (
        rewrite_hass_url(
            hass, "http://example.local:8123/api/tts_proxy/a.mp3?x=1", OVERRIDE
        )
        == f"{OVERRIDE}/api/tts_proxy/a.mp3?x=1"
    )
    assert (
        rewrite_hass_url(hass, "http://example.local:8123/x", "https://ha.example")
        == "https://ha.example/x"
    )
    assert rewrite_hass_url(hass, "http://radio.example/stream", OVERRIDE) == (
        "http://radio.example/stream"
    )


async def test_rewrite_matches_automatic_internal_url(hass: HomeAssistant) -> None:
    """Without a pinned internal_url the automatic one still counts as ours."""
    await async_process_ha_core_config(
        hass, {"external_url": "https://outside.example"}
    )
    hass.config.api = None
    assert hass.config.internal_url is None
    assert (
        rewrite_hass_url(hass, "https://outside.example/api/x.wav", OVERRIDE)
        == f"{OVERRIDE}/api/x.wav"
    )


async def test_play_media_uses_override(hass: HomeAssistant, quick_play_mock) -> None:
    """A device with an override fetches from it and the ledger says so."""
    _, media_status_cb = await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "url_overrides": {str(FakeUUID): OVERRIDE}}
    )
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).attributes["url_override"] == OVERRIDE

    await _play(hass)
    _, app_name, data = quick_play_mock.call_args[0]
    assert app_name == "default_media_receiver"
    assert data["media_id"] == f"{OVERRIDE}/api/tts_proxy/abc.mp3"

    media_status_cb(
        _status(
            content_id=data["media_id"], player_state="BUFFERING", media_session_id=5
        )
    )
    await hass.async_block_till_done()
    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.OK
    assert outcome.attributes["url_source"] == "override"
    assert outcome.attributes["content_id"] == data["media_id"]


async def test_probe_uses_override(hass: HomeAssistant) -> None:
    """The probe URL is re-based per device; other devices keep the global URL."""
    with_override, without = uuid4(), uuid4()
    coordinator, _ = await _bare_coordinator(
        hass, {"url_overrides": {str(with_override): "https://ha.example:8443"}}
    )
    a, b = FakeTarget(), FakeTarget()
    coordinator.async_register_target(with_override, a)
    coordinator.async_register_target(without, b)
    await coordinator.async_refresh()
    await _wait_for(lambda: len(a.plays) == 1 and len(b.plays) == 1)
    assert a.plays[0].startswith("https://ha.example:8443/api/cast/probe/")
    assert b.plays[0].startswith("http://example.local:8123/api/cast/probe/")
    assert a.plays[0].split("/api/")[1] == b.plays[0].split("/api/")[1]


async def test_options_flow_edits_overrides(hass: HomeAssistant) -> None:
    """The health section leads to the override step; set, reject, and clear."""
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"more_options": {}, "health": {"edit_url_overrides": True}},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "url_overrides"
    assert result["description_placeholders"] == {"overrides": "none"}
    device_options = result["data_schema"].schema["device"].config["options"]
    assert device_options == [
        {"value": str(FakeUUID), "label": "Speaker (192.168.178.42)"}
    ]

    # A path is not a base URL.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": str(FakeUUID), "url": f"{OVERRIDE}/api"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"url": "invalid_url"}

    # Set it and ask for another round.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"device": str(FakeUUID), "url": f"{OVERRIDE}/", "add_another": True},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {
        "overrides": f"Speaker (192.168.178.42): {OVERRIDE}"
    }
    assert result["data_schema"].schema["device"].config["options"][0]["label"] == (
        f"Speaker (192.168.178.42) [{OVERRIDE}]"
    )

    # Finish on the second round.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": str(FakeUUID), "url": OVERRIDE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["url_overrides"] == {str(FakeUUID): OVERRIDE}
    assert "edit_url_overrides" not in entry.options
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).attributes["url_override"] == OVERRIDE

    # An empty URL removes the override; the flag itself is never stored.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"more_options": {}, "health": {"edit_url_overrides": True}},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": str(FakeUUID), "url": ""}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["url_overrides"] == {}
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).attributes["url_override"] is None
    assert hass.states.get(ENTITY_ID) is not None


async def test_options_flow_without_edit_flag_is_unchanged(hass: HomeAssistant) -> None:
    """Leaving the flag off finishes on the first step as before."""
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"more_options": {}, "health": {"probe_interval": 90}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["probe_interval"] == 90
    assert "edit_url_overrides" not in entry.options
