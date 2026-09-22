"""Tests for delivery health: outcomes, sensors, events, and the watchdog (WP1)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock, patch

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pychromecast.error import NotConnected, RequestFailed, RequestTimeout
import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.cast.const import EVENT_DELIVERY_RESULT
from custom_components.cast.health import DeliveryOutcome
from tests import media_player_common as common
from tests.test_media_player import (
    async_setup_media_player_cast,
    get_fake_chromecast_info,
    get_status_callbacks,
)

ENTITY_ID = "media_player.speaker"
OUTCOME = "sensor.speaker_tts_outcome"
LAST_SUCCESS = "sensor.speaker_last_tts_success"
MEDIA_URL = "http://example.local:8123/api/tts_proxy/abc.mp3"


def _status(
    content_id: str | None = MEDIA_URL,
    player_state: str = "BUFFERING",
    idle_reason: str | None = None,
    media_session_id: int | None = 2,
    player_is_idle: bool = False,
) -> MagicMock:
    status = MagicMock(images=None)
    status.content_id = content_id
    status.player_state = player_state
    status.idle_reason = idle_reason
    status.media_session_id = media_session_id
    status.player_is_idle = player_is_idle
    return status


async def _setup(hass: HomeAssistant):
    await async_process_ha_core_config(
        hass, {"internal_url": "http://example.local:8123"}
    )
    info = get_fake_chromecast_info()
    chromecast, _ = await async_setup_media_player_cast(hass, info)
    _, conn_status_cb, media_status_cb = get_status_callbacks(chromecast)
    connection_status = MagicMock()
    connection_status.status = "CONNECTED"
    conn_status_cb(connection_status)
    await hass.async_block_till_done()
    return chromecast, media_status_cb


async def _play(hass: HomeAssistant) -> None:
    await common.async_play_media(hass, "audio", MEDIA_URL, ENTITY_ID)
    await hass.async_block_till_done()


async def test_sensors_start_unknown(hass: HomeAssistant) -> None:
    """Both health sensors exist per device and start without evidence."""
    await _setup(hass)
    outcome = hass.states.get(OUTCOME)
    assert outcome is not None
    assert outcome.state == DeliveryOutcome.UNKNOWN
    assert outcome.attributes["content_id"] is None
    assert outcome.attributes["host"] == "192.168.178.42"
    assert hass.states.get(LAST_SUCCESS).state == "unknown"


async def test_mdns_visible_but_unreachable(hass: HomeAssistant) -> None:
    """Discovery succeeds, the device cannot fetch the media, outcome is fetch_failed.

    This replays the 2026-09-21 incident: the cast accepted the command and
    then went idle with reason ERROR. The outcome must never read ok.
    """
    _, media_status_cb = await _setup(hass)
    events = async_capture_events(hass, EVENT_DELIVERY_RESULT)

    await _play(hass)
    media_status_cb(_status(player_state="IDLE", idle_reason="ERROR", player_is_idle=True))
    await hass.async_block_till_done()

    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.FETCH_FAILED
    assert outcome.attributes["url_source"] == "internal_url"
    assert outcome.attributes["responded"] is True
    assert outcome.attributes["content_id"] == MEDIA_URL
    assert "idleReason=ERROR" in outcome.attributes["error"]
    assert outcome.attributes["consecutive_failures"] == 1
    assert hass.states.get(LAST_SUCCESS).state == "unknown"

    assert len(events) == 1
    data = events[0].data
    assert data["outcome"] == "fetch_failed"
    assert data["entity_id"] == ENTITY_ID
    assert data["content_id"] == MEDIA_URL
    assert data["source"] == "play_media"
    assert data["elapsed"] is not None


async def test_delivery_ok_sets_last_success(hass: HomeAssistant) -> None:
    """BUFFERING for the requested content id with a new session resolves ok."""
    _, media_status_cb = await _setup(hass)
    await _play(hass)
    media_status_cb(_status(player_state="BUFFERING", media_session_id=7))
    await hass.async_block_till_done()

    assert hass.states.get(OUTCOME).state == DeliveryOutcome.OK
    assert hass.states.get(LAST_SUCCESS).state != "unknown"

    # A later failure keeps the last success timestamp.
    last_success = hass.states.get(LAST_SUCCESS).state
    await _play(hass)
    media_status_cb(_status(player_state="IDLE", idle_reason="ERROR", player_is_idle=True))
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.FETCH_FAILED
    assert hass.states.get(LAST_SUCCESS).state == last_success


async def test_timeout_not_recorded_as_success(hass: HomeAssistant) -> None:
    """An expired wait leaves last_tts_success untouched and reports timeout."""
    _, media_status_cb = await _setup(hass)
    await _play(hass)
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.UNKNOWN

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()

    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.TIMEOUT
    assert outcome.attributes["responded"] is False
    assert hass.states.get(LAST_SUCCESS).state == "unknown"

    # A status arriving after the timeout does not retroactively succeed.
    media_status_cb(_status(player_state="PLAYING", media_session_id=9))
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.TIMEOUT


async def test_stale_metadata_not_treated_as_confirmation(hass: HomeAssistant) -> None:
    """Per pychromecast #1018, unchanged metadata does not satisfy a success check."""
    chromecast, media_status_cb = await _setup(hass)
    # The device is already playing the same URL from an earlier announcement.
    chromecast.media_controller.status = _status(player_state="PLAYING", media_session_id=5)
    media_status_cb(chromecast.media_controller.status)
    await hass.async_block_till_done()

    await _play(hass)
    # Same content id and the same session id as at request time: no evidence.
    media_status_cb(_status(player_state="PLAYING", media_session_id=5))
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.UNKNOWN

    # A status for a different content id is ignored too.
    media_status_cb(_status(content_id="http://other/x.mp3", media_session_id=6))
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.UNKNOWN

    # A new session for the requested content id is evidence.
    media_status_cb(_status(player_state="PLAYING", media_session_id=6))
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.OK


async def test_error_for_other_content_is_observed_not_resolved(
    hass: HomeAssistant,
) -> None:
    """An ERROR for media we did not request is recorded but keeps ours pending."""
    _, media_status_cb = await _setup(hass)
    events = async_capture_events(hass, EVENT_DELIVERY_RESULT)
    await _play(hass)
    media_status_cb(
        _status(
            content_id="http://other/x.mp3",
            player_state="IDLE",
            idle_reason="ERROR",
            player_is_idle=True,
        )
    )
    await hass.async_block_till_done()
    assert events[0].data["source"] == "observed"
    assert events[0].data["outcome"] == "fetch_failed"

    media_status_cb(_status(player_state="BUFFERING", media_session_id=3))
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.OK


async def test_unsolicited_error_without_request(hass: HomeAssistant) -> None:
    """An ERROR with no pending request still surfaces as fetch_failed."""
    _, media_status_cb = await _setup(hass)
    media_status_cb(_status(player_state="IDLE", idle_reason="ERROR", player_is_idle=True))
    await hass.async_block_till_done()
    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.FETCH_FAILED
    assert outcome.attributes["source"] == "observed"


async def test_load_media_failed_resolves_pending(hass: HomeAssistant) -> None:
    """A LOAD_FAILED callback is a device-reported fetch failure."""
    chromecast, _ = await _setup(hass)
    await _play(hass)
    listener = chromecast.socket_client.media_controller.register_status_listener.call_args[
        0
    ][0]
    listener.load_media_failed(1, 104)
    await hass.async_block_till_done()
    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.FETCH_FAILED
    assert "MEDIA_SRC_NOT_SUPPORTED" in outcome.attributes["error"]

    # Without a pending request the callback is only logged.
    listener.load_media_failed(2, 100)
    await hass.async_block_till_done()
    assert outcome.attributes["error"] == hass.states.get(OUTCOME).attributes["error"]


@pytest.mark.parametrize(
    ("exc", "expected", "responded"),
    [
        (RequestTimeout("quick play", 30.0), DeliveryOutcome.TIMEOUT, False),
        (NotConnected(), DeliveryOutcome.UNREACHABLE, False),
        (RequestFailed("quick play"), DeliveryOutcome.UNREACHABLE, False),
    ],
)
async def test_request_exception_classification(
    hass: HomeAssistant, quick_play_mock, exc, expected, responded
) -> None:
    """Exceptions from the play request map onto the outcome vocabulary."""
    await _setup(hass)
    quick_play_mock.side_effect = exc
    with pytest.raises(HomeAssistantError):
        await _play(hass)
    outcome = hass.states.get(OUTCOME)
    assert outcome.state == expected
    assert outcome.attributes["responded"] is responded
    assert type(exc).__name__ in outcome.attributes["error"]


async def test_hung_play_request_hits_watchdog(hass: HomeAssistant, quick_play_mock) -> None:
    """A quick_play that never returns (pychromecast #1247) is cut by the watchdog."""
    await _setup(hass)
    release = asyncio.Event()

    def hang(*_args):
        asyncio.run_coroutine_threadsafe(release.wait(), hass.loop).result()

    quick_play_mock.side_effect = hang
    with (
        patch("custom_components.cast.media_player.REQUEST_WATCHDOG", 0.05),
        pytest.raises(HomeAssistantError, match="did not answer"),
    ):
        await _play(hass)
    release.set()
    await hass.async_block_till_done()
    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.TIMEOUT
    assert outcome.attributes["responded"] is False
    assert "TimeoutError" in outcome.attributes["error"]


async def test_superseded_request_is_unknown_not_failure(hass: HomeAssistant) -> None:
    """A second request before the first resolves records unknown, not a failure."""
    _, media_status_cb = await _setup(hass)
    events = async_capture_events(hass, EVENT_DELIVERY_RESULT)
    await _play(hass)
    await _play(hass)
    assert events[0].data["outcome"] == "unknown"
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.UNKNOWN
    assert hass.states.get(OUTCOME).attributes["consecutive_failures"] == 0

    media_status_cb(_status(player_state="PLAYING", media_session_id=4))
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.OK


async def test_cast_app_play_is_tracked(hass: HomeAssistant, quick_play_mock) -> None:
    """Playing through a named cast app goes through the same ledger."""
    _, media_status_cb = await _setup(hass)
    await common.async_play_media(
        hass, "cast", '{"app_name": "youtube", "media_id": "abc"}', ENTITY_ID
    )
    await hass.async_block_till_done()
    quick_play_mock.assert_called_once()
    media_status_cb(_status(content_id="abc", player_state="PLAYING", media_session_id=3))
    await hass.async_block_till_done()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.OK
    assert hass.states.get(OUTCOME).attributes["url_source"] is None


async def test_last_success_restored_after_restart(hass: HomeAssistant) -> None:
    """The last success timestamp survives a restart through restore state."""
    from pytest_homeassistant_custom_component.common import (
        mock_restore_cache_with_extra_data,
    )

    stamp = "2026-09-21T10:00:00+00:00"
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(LAST_SUCCESS, stamp),
                {"native_value": stamp, "native_unit_of_measurement": None},
            ),
        ),
    )
    await _setup(hass)
    assert hass.states.get(LAST_SUCCESS).state == stamp


async def test_unload_entry_stops_discovery(hass: HomeAssistant, castbrowser_mock) -> None:
    """Unloading the entry stops discovery and releases the discovery lock."""
    from custom_components.cast.const import INTERNAL_DISCOVERY_RUNNING_KEY

    await _setup(hass)
    entry = hass.config_entries.async_entries("cast")[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.data[INTERNAL_DISCOVERY_RUNNING_KEY].locked()
    assert hass.states.get(OUTCOME).state == STATE_UNAVAILABLE
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_health_sensor_device_record_matches_media_player(hass: HomeAssistant) -> None:
    """The sensors carry the cast name so the device is named correctly either way.

    On a slow runner the sensor platform can register the device before the
    media player does; without the name the device would be called after the
    config entry title and the entity ids would follow it.
    """
    from custom_components.cast.sensor import CastOutcomeSensor
    from tests.test_media_player import get_fake_chromecast_info

    entry = hass.config_entries.async_entries("cast")
    assert not entry
    info = get_fake_chromecast_info()
    sensor = CastOutcomeSensor(MagicMock(), info)
    assert sensor.device_info["name"] == "Speaker"
    assert sensor.device_info["manufacturer"] == "Nabu Casa"
    assert sensor.device_info["model"] == "Chromecast"
    assert sensor.unique_id == f"{info.uuid}_tts_outcome"
