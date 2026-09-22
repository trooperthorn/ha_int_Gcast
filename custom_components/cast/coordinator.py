"""Active reachability probing on a DataUpdateCoordinator (WP2).

Probes run off the coordinator's critical path, behind a watchdog, with a
per-device circuit breaker. The policy is in DESIGN.md section 9.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from pychromecast.controllers.media import (
    MEDIA_PLAYER_STATE_BUFFERING,
    MEDIA_PLAYER_STATE_PAUSED,
    MEDIA_PLAYER_STATE_PLAYING,
)

from .const import (
    CIRCUIT_BREAKER_MAX_BACKOFF,
    CIRCUIT_BREAKER_TIMEOUTS,
    CONF_GROUP_PROBE_ENABLED,
    CONF_PROBE_ENABLED,
    CONF_PROBE_INTERVAL,
    CONF_PROBE_VIDEO_DEVICES,
    DELIVERY_TIMEOUT,
    DOMAIN,
    HEALTH_DEFAULTS,
    MIN_PROBE_INTERVAL,
    PROBE_WATCHDOG,
)
from .health import DeliveryLedger, DeliveryOutcome, DeliveryRecord, DeviceHealth
from .probe import PROBE_CONTENT_TYPE, async_setup_probe_view
from .urls import rewrite_hass_url, url_overrides

if TYPE_CHECKING:
    from . import CastConfigEntry

_LOGGER = logging.getLogger(__name__)

BUSY_STATES = frozenset(
    {
        MEDIA_PLAYER_STATE_PLAYING,
        MEDIA_PLAYER_STATE_BUFFERING,
        MEDIA_PLAYER_STATE_PAUSED,
    }
)


@dataclass(frozen=True, slots=True)
class ProbeSnapshot:
    """What the entity knows about the device at the moment a probe is due."""

    cast_type: str | None
    is_audio_group: bool
    app_id: str | None
    app_idle: bool
    player_state: str | None
    group_player_states: tuple[str | None, ...]
    media_session_id: int | None

    @property
    def busy(self) -> bool:
        """Return True when playback would be interrupted by a probe."""
        if self.player_state in BUSY_STATES:
            return True
        return any(state in BUSY_STATES for state in self.group_player_states)


class ProbeTarget(Protocol):
    """What a media player entity exposes to the probe coordinator."""

    def probe_snapshot(self) -> ProbeSnapshot | None:
        """Return the current snapshot, or None when not connected."""

    def quick_play_probe(self, url: str, content_type: str) -> None:
        """Play the probe clip; runs in the executor."""

    def quit_app_probe(self) -> None:
        """Quit the app the probe launched; runs in the executor."""


@dataclass(slots=True)
class ProbeResult:
    """Last probe decision for a device, for diagnostics."""

    checked_at: datetime
    decision: str
    outcome: DeliveryOutcome | None = None


@dataclass(frozen=True, slots=True)
class ProbeOptions:
    """Options that govern probing."""

    enabled: bool
    interval: int
    groups: bool
    video: bool


def probe_options(entry: CastConfigEntry) -> ProbeOptions:
    """Read the probe options with their floors applied."""
    options = {**HEALTH_DEFAULTS, **entry.options}
    return ProbeOptions(
        enabled=bool(options[CONF_PROBE_ENABLED]),
        interval=max(int(options[CONF_PROBE_INTERVAL]), MIN_PROBE_INTERVAL),
        groups=bool(options[CONF_GROUP_PROBE_ENABLED]),
        video=bool(options[CONF_PROBE_VIDEO_DEVICES]),
    )


class CastProbeCoordinator(DataUpdateCoordinator[dict[UUID, ProbeResult]]):
    """Schedule probes; never wait on a device inside the refresh."""

    config_entry: CastConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: CastConfigEntry, ledger: DeliveryLedger
    ) -> None:
        """Initialize the coordinator."""
        self.options = probe_options(entry)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} probe",
            update_interval=timedelta(seconds=self.options.interval),
        )
        self.ledger = ledger
        self.targets: dict[UUID, ProbeTarget] = {}
        self._running: set[UUID] = set()
        self._unsub_ledger: CALLBACK_TYPE | None = ledger.async_add_listener(
            self._async_on_record
        )
        self._unsub_keepalive: CALLBACK_TYPE | None = self.async_add_listener(
            lambda: None
        )

    @callback
    def async_apply_options(self) -> None:
        """Re-read the options after the entry was updated."""
        self.options = probe_options(self.config_entry)
        self.update_interval = timedelta(seconds=self.options.interval)  # type: ignore[misc]
        _LOGGER.debug(
            "probe options applied enabled=%s interval=%ss groups=%s video=%s",
            self.options.enabled,
            self.options.interval,
            self.options.groups,
            self.options.video,
        )

    @callback
    def async_register_target(self, uuid: UUID, target: ProbeTarget) -> CALLBACK_TYPE:
        """Register a device to probe; returns the unregister callable."""
        self.targets[uuid] = target

        @callback
        def _unregister() -> None:
            if self.targets.get(uuid) is target:
                del self.targets[uuid]

        return _unregister

    @callback
    def async_shutdown_probes(self) -> None:
        """Detach from the ledger and stop scheduling."""
        if self._unsub_ledger is not None:
            self._unsub_ledger()
            self._unsub_ledger = None
        if self._unsub_keepalive is not None:
            self._unsub_keepalive()
            self._unsub_keepalive = None

    async def _async_update_data(self) -> dict[UUID, ProbeResult]:
        """Decide, per device, whether to launch a probe; return immediately."""
        results = dict(self.data or {})
        if (topology := self.config_entry.runtime_data.topology) is not None:
            await topology.async_refresh()
            if (repairs := self.config_entry.runtime_data.repairs) is not None:
                repairs.async_check_topology(topology)
                repairs.async_check_stale(set(topology.infos))
        if not self.options.enabled:
            _LOGGER.debug("probe cycle skipped: probing disabled in options")
            return results

        try:
            # The same base-URL choice TTS playback makes, without a signature:
            # the TTS proxy path is unsigned too and some devices reject long URLs.
            url = f"{get_url(self.hass)}{async_setup_probe_view(self.hass)}"
        except NoURLAvailableError as err:
            raise UpdateFailed(
                "no internal or external URL is configured; probing needs one"
            ) from err
        overrides = url_overrides(self.config_entry)
        now = dt_util.utcnow()
        for uuid, target in list(self.targets.items()):
            health = self.ledger.device(uuid)
            decision = self._decide(uuid, target, health)
            results[uuid] = ProbeResult(checked_at=now, decision=decision)
            if decision != "probe":
                _LOGGER.debug(
                    "[%s %s uuid=%s] probe %s",
                    health.entity_id,
                    health.name,
                    uuid,
                    decision,
                )
                continue
            snapshot = target.probe_snapshot()
            assert snapshot is not None
            self._running.add(uuid)
            device_url = url
            if (base := overrides.get(uuid)) is not None:
                device_url = rewrite_hass_url(self.hass, url, base)
            self.hass.async_create_background_task(
                self._async_probe(uuid, target, snapshot, device_url),
                f"cast-probe-{uuid}",
                eager_start=True,
            )
        return results

    def _decide(self, uuid: UUID, target: ProbeTarget, health: DeviceHealth) -> str:
        if uuid in self._running:
            return "skipped: previous probe still running"
        snapshot = target.probe_snapshot()
        if snapshot is None:
            # A device with no Cast channel is the silent failure the fork
            # exists for; record it instead of skipping quietly.
            self.ledger.async_record(
                uuid,
                DeliveryOutcome.UNREACHABLE,
                source="probe",
                error="no Cast channel to the device on port 8009 (entity unavailable)",
            )
            return "unreachable: not connected"
        if snapshot.is_audio_group and not self.options.groups:
            return "skipped: group probing disabled"
        if (
            not snapshot.is_audio_group
            and snapshot.cast_type not in ("audio", None)
            and not self.options.video
        ):
            return "skipped: video devices are not probed (CEC could wake a display)"
        if health.circuit_open_until is not None:
            remaining = health.circuit_open_until - time.monotonic()
            if remaining > 0:
                return f"skipped: circuit open for {remaining:.0f}s more"
            _LOGGER.debug(
                "[%s %s uuid=%s] circuit half-open, probing once",
                health.entity_id,
                health.name,
                uuid,
            )
        if snapshot.busy:
            self.ledger.async_record(
                uuid,
                DeliveryOutcome.SKIPPED_BUSY,
                source="probe",
                error=(
                    f"device not idle: player_state={snapshot.player_state} "
                    f"group_states={list(snapshot.group_player_states)} app_id={snapshot.app_id}"
                ),
            )
            return "skipped_busy"
        return "probe"

    async def _async_probe(
        self, uuid: UUID, target: ProbeTarget, snapshot: ProbeSnapshot, url: str
    ) -> None:
        health = self.ledger.device(uuid)
        prefix = f"[{health.entity_id} {health.name} uuid={uuid}]"
        try:
            self.ledger.async_begin_request(
                uuid, url, "probe", snapshot.media_session_id, timeout=DELIVERY_TIMEOUT
            )
            _LOGGER.debug(
                "%s probe started url=%s app_idle_before=%s app_id=%s",
                prefix,
                url,
                snapshot.app_idle,
                snapshot.app_id,
            )
            try:
                async with asyncio.timeout(PROBE_WATCHDOG):
                    await self.hass.async_add_executor_job(
                        target.quick_play_probe, url, PROBE_CONTENT_TYPE
                    )
            except (TimeoutError, HomeAssistantError) as err:
                self.ledger.async_request_failed(uuid, err)
                return

            outcome = await self._async_wait_for_outcome(uuid)
            if outcome is DeliveryOutcome.OK and snapshot.app_idle:
                await self._async_restore_idle(uuid, target, prefix)
        finally:
            self._running.discard(uuid)
            if self.data is not None and uuid in self.data:
                self.data[uuid].outcome = (
                    health.last_record.outcome if health.last_record else None
                )
            self.async_update_listeners()

    async def _async_wait_for_outcome(self, uuid: UUID) -> DeliveryOutcome | None:
        """Wait until the ledger resolves the probe request (bounded)."""
        health = self.ledger.device(uuid)
        deadline = time.monotonic() + DELIVERY_TIMEOUT + 5
        while health.pending is not None and health.pending.source == "probe":
            if time.monotonic() > deadline:
                return None
            await asyncio.sleep(0.25)
        return health.last_record.outcome if health.last_record else None

    async def _async_restore_idle(
        self, uuid: UUID, target: ProbeTarget, prefix: str
    ) -> None:
        """Quit the media receiver the probe launched on a previously idle device."""
        try:
            async with asyncio.timeout(PROBE_WATCHDOG):
                await self.hass.async_add_executor_job(target.quit_app_probe)
        except (TimeoutError, HomeAssistantError) as err:
            _LOGGER.debug("%s could not quit the probe app: %s", prefix, err)
        else:
            _LOGGER.debug("%s probe app quit, device returned to idle", prefix)

    @callback
    def _async_on_record(self, health: DeviceHealth, record: DeliveryRecord) -> None:
        """Drive the circuit breaker from probe outcomes."""
        if record.source != "probe":
            return
        if record.outcome is DeliveryOutcome.OK:
            if health.circuit_open_until is not None:
                _LOGGER.info(
                    "[%s %s uuid=%s] circuit closed after a successful probe",
                    health.entity_id,
                    health.name,
                    health.uuid,
                )
            health.circuit_open_until = None
            return
        if (
            record.outcome is DeliveryOutcome.TIMEOUT
            and health.consecutive_timeouts >= CIRCUIT_BREAKER_TIMEOUTS
        ):
            exponent = health.consecutive_timeouts - CIRCUIT_BREAKER_TIMEOUTS + 1
            backoff = min(
                self.options.interval * 2**exponent, CIRCUIT_BREAKER_MAX_BACKOFF
            )
            health.circuit_open_until = time.monotonic() + backoff
            _LOGGER.warning(
                "[%s %s uuid=%s] circuit open: %d consecutive probe timeouts "
                "(responded=%s); next probe in %ds. A device that never answers "
                "matches pychromecast #1247 (hung app launch); power-cycle it if "
                "playback is also failing",
                health.entity_id,
                health.name,
                health.uuid,
                health.consecutive_timeouts,
                record.responded,
                backoff,
            )
