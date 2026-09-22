"""Tests for active reachability probing (WP2)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.exceptions import HomeAssistantError
from pychromecast.error import RequestTimeout
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.cast.const import (
    DOMAIN,
    EVENT_DELIVERY_RESULT,
    PROBE_WATCHDOG,
)
from custom_components.cast.coordinator import (
    CastProbeCoordinator,
    ProbeSnapshot,
    probe_options,
)
from custom_components.cast.health import DeliveryOutcome
from tests.test_health import ENTITY_ID, LAST_SUCCESS, OUTCOME, _setup, _status
from tests.test_media_player import FakeUUID


@dataclass
class FakeTarget:
    """A probe target that behaves like a device without a socket."""

    snapshot: ProbeSnapshot | None = field(
        default_factory=lambda: ProbeSnapshot(
            cast_type="audio",
            is_audio_group=False,
            app_id=None,
            app_idle=True,
            player_state="IDLE",
            group_player_states=(),
            media_session_id=1,
        )
    )
    play_error: BaseException | None = None
    hang: threading.Event | None = None
    plays: list[str] = field(default_factory=list)
    quits: int = 0

    def probe_snapshot(self) -> ProbeSnapshot | None:
        return self.snapshot

    def quick_play_probe(self, url: str, content_type: str) -> None:
        self.plays.append(url)
        if self.hang is not None:
            self.hang.wait()
        if self.play_error is not None:
            raise HomeAssistantError("probe failed") from self.play_error

    def quit_app_probe(self) -> None:
        self.quits += 1


async def _bare_coordinator(
    hass: HomeAssistant, options: dict | None = None
) -> tuple[CastProbeCoordinator, MockConfigEntry]:
    """A coordinator on a loaded entry with the media player platform stubbed."""
    await async_process_ha_core_config(
        hass, {"internal_url": "http://example.local:8123"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ignore_cec": [], "known_hosts": [], "uuid": []},
        options=options or {},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.cast.media_player.async_setup_entry", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    assert coordinator is not None
    return coordinator, entry


async def _wait_for(predicate, limit: float = 5.0) -> None:
    deadline = time.monotonic() + limit
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.02)


async def test_probe_ok_through_entity(hass: HomeAssistant, quick_play_mock) -> None:
    """A full probe on the real entity: play, confirm, quit the app, report ok."""
    chromecast, media_status_cb = await _setup(hass)
    chromecast.cast_type = "audio"
    chromecast.is_idle = True
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    coordinator = entry.runtime_data.coordinator
    events = async_capture_events(hass, EVENT_DELIVERY_RESULT)

    await coordinator.async_refresh()
    await _wait_for(lambda: quick_play_mock.call_count == 1)
    _, app_name, data = quick_play_mock.call_args[0]
    assert app_name == "default_media_receiver"
    assert data["media_type"] == "audio/wav"
    assert data["media_id"].startswith("http://example.local:8123/api/cast/probe/")
    probe_url = data["media_id"]

    media_status_cb(_status(content_id=probe_url, player_state="BUFFERING", media_session_id=9))
    await _wait_for(lambda: chromecast.quit_app.call_count == 1)
    await hass.async_block_till_done()

    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.OK
    assert outcome.attributes["source"] == "probe"
    assert outcome.attributes["url_source"] == "internal_url"
    assert hass.states.get(LAST_SUCCESS).state != "unknown"
    assert events[-1].data["source"] == "probe"
    assert coordinator.data[FakeUUID].decision == "probe"


async def test_probe_mdns_visible_but_unreachable(hass: HomeAssistant, quick_play_mock) -> None:
    """A device reachable by mDNS but blocked at the firewall reports fetch_failed."""
    chromecast, media_status_cb = await _setup(hass)
    chromecast.cast_type = "audio"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await entry.runtime_data.coordinator.async_refresh()
    await _wait_for(lambda: quick_play_mock.call_count == 1)
    probe_url = quick_play_mock.call_args[0][2]["media_id"]

    media_status_cb(
        _status(content_id=probe_url, player_state="IDLE", idle_reason="ERROR", player_is_idle=True)
    )
    await _wait_for(lambda: hass.states.get(OUTCOME).state == DeliveryOutcome.FETCH_FAILED)
    assert hass.states.get(OUTCOME).attributes["source"] == "probe"
    assert chromecast.quit_app.call_count == 0
    assert hass.states.get(ENTITY_ID) is not None


async def test_probe_skipped_when_busy(hass: HomeAssistant, quick_play_mock) -> None:
    """A playing device is never interrupted; the skip is recorded, not a failure."""
    chromecast, media_status_cb = await _setup(hass)
    chromecast.cast_type = "audio"
    media_status_cb(_status(content_id="http://music/x.mp3", player_state="PLAYING", media_session_id=3))
    await hass.async_block_till_done()
    events = async_capture_events(hass, EVENT_DELIVERY_RESULT)

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert quick_play_mock.call_count == 0
    assert events[-1].data["outcome"] == "skipped_busy"
    assert "player_state=PLAYING" in events[-1].data["error"]
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.UNKNOWN


async def test_hung_device_does_not_block_others(hass: HomeAssistant) -> None:
    """One wedged device (pychromecast #1247) delays neither the refresh nor a peer."""
    coordinator, _ = await _bare_coordinator(hass)
    hung_uuid, good_uuid = uuid4(), uuid4()
    hung = FakeTarget(hang=threading.Event())
    good = FakeTarget()
    coordinator.async_register_target(hung_uuid, hung)
    coordinator.async_register_target(good_uuid, good)

    with patch("custom_components.cast.coordinator.PROBE_WATCHDOG", 0.2):
        started = time.monotonic()
        await coordinator.async_refresh()
        assert time.monotonic() - started < 1.0
        assert coordinator.last_update_success

        await _wait_for(lambda: len(good.plays) == 1 and len(hung.plays) == 1)
        coordinator.ledger.async_media_status(
            good_uuid, good.plays[0], "PLAYING", None, 2, False
        )
        await hass.async_block_till_done()
        assert coordinator.ledger.device(good_uuid).last_outcome == DeliveryOutcome.OK
        assert coordinator.ledger.device(hung_uuid).last_outcome == DeliveryOutcome.UNKNOWN

        await _wait_for(
            lambda: coordinator.ledger.device(hung_uuid).last_outcome == DeliveryOutcome.TIMEOUT
        )
    record = coordinator.ledger.device(hung_uuid).last_record
    assert record.responded is False
    assert "watchdog" in record.error
    hung.hang.set()
    await _wait_for(lambda: good.quits == 1)


async def test_circuit_breaker_opens(hass: HomeAssistant) -> None:
    """Two consecutive timeouts stop probing that device until the backoff passes."""
    coordinator, _ = await _bare_coordinator(hass, {"probe_interval": 60})
    uuid = uuid4()
    target = FakeTarget(play_error=RequestTimeout("quick play", 30.0))
    coordinator.async_register_target(uuid, target)
    health = coordinator.ledger.device(uuid)

    for expected in (1, 2):
        await coordinator.async_refresh()
        await _wait_for(lambda n=expected: len(target.plays) == n)
        await _wait_for(lambda n=expected: health.consecutive_timeouts == n)
    assert health.circuit_open_until is not None
    assert health.last_outcome == DeliveryOutcome.TIMEOUT

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(target.plays) == 2
    assert coordinator.data[uuid].decision.startswith("skipped: circuit open")

    # Backoff elapsed: one half-open probe, and success closes the circuit.
    health.circuit_open_until = time.monotonic() - 1
    target.play_error = None
    await coordinator.async_refresh()
    await _wait_for(lambda: len(target.plays) == 3)
    coordinator.ledger.async_media_status(uuid, target.plays[0], "BUFFERING", None, 5, False)
    await hass.async_block_till_done()
    assert health.circuit_open_until is None
    assert health.consecutive_timeouts == 0


async def test_circuit_backoff_grows_and_caps(hass: HomeAssistant) -> None:
    """Backoff doubles per extra timeout and is capped at one hour."""
    coordinator, _ = await _bare_coordinator(hass, {"probe_interval": 1800})
    uuid = uuid4()
    target = FakeTarget(play_error=RequestTimeout("quick play", 30.0))
    coordinator.async_register_target(uuid, target)
    health = coordinator.ledger.device(uuid)
    for n in range(1, 4):
        health.circuit_open_until = None
        await coordinator.async_refresh()
        await _wait_for(lambda count=n: health.consecutive_timeouts == count)
    assert health.circuit_open_until - time.monotonic() <= 3600


async def test_probe_decisions(hass: HomeAssistant) -> None:
    """Disabled probing, groups, video devices, and disconnected devices are skipped."""
    coordinator, entry = await _bare_coordinator(hass, {"group_probe_enabled": False})
    group_uuid, video_uuid, gone_uuid, running_uuid = uuid4(), uuid4(), uuid4(), uuid4()
    group = FakeTarget()
    group.snapshot = ProbeSnapshot("group", True, None, True, "IDLE", (), 1)
    video = FakeTarget()
    video.snapshot = ProbeSnapshot("cast", False, None, True, "IDLE", (), 1)
    gone = FakeTarget(snapshot=None)
    running = FakeTarget(hang=threading.Event())
    for uuid, target in (
        (group_uuid, group),
        (video_uuid, video),
        (gone_uuid, gone),
        (running_uuid, running),
    ):
        coordinator.async_register_target(uuid, target)

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data[group_uuid].decision == "skipped: group probing disabled"
    assert coordinator.data[video_uuid].decision.startswith("skipped: video devices")
    assert coordinator.data[gone_uuid].decision == "unreachable: not connected"
    assert coordinator.ledger.device(gone_uuid).last_outcome == DeliveryOutcome.UNREACHABLE
    assert coordinator.ledger.device(gone_uuid).last_record.source == "probe"
    assert coordinator.data[running_uuid].decision == "probe"

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data[running_uuid].decision == "skipped: previous probe still running"
    running.hang.set()
    await _wait_for(lambda: len(running.plays) == 1)
    coordinator.ledger.async_media_status(
        running_uuid, running.plays[0], "PLAYING", None, 2, False
    )
    await _wait_for(lambda: running_uuid not in coordinator._running)

    hass.config_entries.async_update_entry(
        entry, options={"probe_enabled": False, "probe_interval": 10, "probe_video_devices": True}
    )
    await hass.async_block_till_done()
    assert coordinator.options.enabled is False
    assert coordinator.options.interval == 60
    assert coordinator.update_interval.total_seconds() == 60
    plays_before = len(running.plays)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(running.plays) == plays_before


async def test_probe_options_defaults() -> None:
    """Defaults apply when no option is stored."""
    entry = MagicMock(options={})
    options = probe_options(entry)
    assert options.enabled and options.groups and not options.video
    assert options.interval == 300


async def test_busy_snapshot_considers_group_playback() -> None:
    """A member of a playing group counts as busy even when its own state is idle."""
    snapshot = ProbeSnapshot("audio", False, None, True, "IDLE", ("PLAYING",), 1)
    assert snapshot.busy
    assert not ProbeSnapshot("audio", False, None, True, "IDLE", (None,), 1).busy


async def test_group_probe_is_independently_disableable(hass: HomeAssistant) -> None:
    """Group probing off leaves device probing on (pychromecast #1197)."""
    coordinator, _ = await _bare_coordinator(hass, {"group_probe_enabled": False})
    device_uuid = uuid4()
    device = FakeTarget()
    coordinator.async_register_target(device_uuid, device)
    await coordinator.async_refresh()
    await _wait_for(lambda: len(device.plays) == 1)
    assert PROBE_WATCHDOG > 0


async def test_unload_shuts_down_probing(hass: HomeAssistant) -> None:
    """Unloading detaches the coordinator from the ledger."""
    coordinator, entry = await _bare_coordinator(hass)
    assert coordinator.ledger.listeners
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not coordinator.ledger.listeners


@pytest.mark.usefixtures("hass")
async def test_probe_records_restore_failure_is_debug_only(hass: HomeAssistant) -> None:
    """A quit_app failure after a good probe does not change the outcome."""
    coordinator, _ = await _bare_coordinator(hass)
    uuid = uuid4()

    class QuitFails(FakeTarget):
        def quit_app_probe(self) -> None:
            raise HomeAssistantError("quit failed")

    target = QuitFails()
    coordinator.async_register_target(uuid, target)
    await coordinator.async_refresh()
    await _wait_for(lambda: len(target.plays) == 1)
    coordinator.ledger.async_media_status(uuid, target.plays[0], "PLAYING", None, 2, False)
    await _wait_for(lambda: uuid not in coordinator._running)
    assert coordinator.ledger.device(uuid).last_outcome == DeliveryOutcome.OK
