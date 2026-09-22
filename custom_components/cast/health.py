"""Delivery health: turn Cast media status callbacks into observable state.

Design and the outcome vocabulary are in DESIGN.md; the threading rules
(callbacks arrive on pychromecast's socket thread) are in docs/design.md.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util
from pychromecast.controllers.media import (
    MEDIA_PLAYER_ERROR_CODES,
    MEDIA_PLAYER_STATE_BUFFERING,
    MEDIA_PLAYER_STATE_PLAYING,
)
from pychromecast.error import (
    ChromecastConnectionError,
    NotConnected,
    PyChromecastError,
    RequestFailed,
    RequestTimeout,
)

from .const import (
    DELIVERY_TIMEOUT,
    EVENT_DELIVERY_RESULT,
    LEDGER_SIZE,
    SIGNAL_HEALTH_UPDATED,
)

if TYPE_CHECKING:
    from . import CastConfigEntry

_LOGGER = logging.getLogger(__name__)

IDLE_REASON_ERROR = "ERROR"


class DeliveryOutcome(StrEnum):
    """Closed set of delivery outcomes; see DESIGN.md section 3."""

    OK = "ok"
    FETCH_FAILED = "fetch_failed"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    TEMPLATE_ERROR = "template_error"
    SKIPPED_BUSY = "skipped_busy"
    UNKNOWN = "unknown"


FAILURE_OUTCOMES = frozenset(
    {
        DeliveryOutcome.FETCH_FAILED,
        DeliveryOutcome.UNREACHABLE,
        DeliveryOutcome.TIMEOUT,
        DeliveryOutcome.TEMPLATE_ERROR,
    }
)


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """One resolved delivery attempt or observation."""

    uuid: UUID
    entity_id: str | None
    name: str | None
    source: str
    outcome: DeliveryOutcome
    content_id: str | None
    error: str | None
    url_source: str | None
    responded: bool
    requested_at: datetime | None
    resolved_at: datetime
    elapsed: float | None
    player_state: str | None
    idle_reason: str | None
    media_session_id: int | None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for events and diagnostics."""
        return {
            "uuid": str(self.uuid),
            "entity_id": self.entity_id,
            "name": self.name,
            "source": self.source,
            "outcome": self.outcome.value,
            "content_id": self.content_id,
            "error": self.error,
            "url_source": self.url_source,
            "responded": self.responded,
            "requested_at": (
                self.requested_at.isoformat() if self.requested_at else None
            ),
            "resolved_at": self.resolved_at.isoformat(),
            "elapsed": self.elapsed,
            "player_state": self.player_state,
            "idle_reason": self.idle_reason,
            "media_session_id": self.media_session_id,
        }


@dataclass(slots=True)
class PendingRequest:
    """A play request waiting for the device to acknowledge or fail it."""

    content_id: str
    source: str
    requested_at: datetime
    started: float
    session_at_request: int | None
    cancel_timeout: CALLBACK_TYPE | None = None


@dataclass(slots=True)
class DeviceHealth:
    """Per-device delivery state."""

    uuid: UUID
    entity_id: str | None = None
    name: str | None = None
    host: str | None = None
    port: int | None = None
    last_outcome: DeliveryOutcome = DeliveryOutcome.UNKNOWN
    last_record: DeliveryRecord | None = None
    last_success: datetime | None = None
    last_seen: datetime | None = None
    consecutive_failures: int = 0
    consecutive_timeouts: int = 0
    circuit_open_until: float | None = None
    subnet_mismatch: bool | None = None
    pending: PendingRequest | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for diagnostics."""
        return {
            "uuid": str(self.uuid),
            "entity_id": self.entity_id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "last_outcome": self.last_outcome.value,
            "last_success": (
                self.last_success.isoformat() if self.last_success else None
            ),
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_timeouts": self.consecutive_timeouts,
            "circuit_open": self.circuit_open_until is not None
            and self.circuit_open_until > time.monotonic(),
            "subnet_mismatch": self.subnet_mismatch,
            "pending_content_id": self.pending.content_id if self.pending else None,
            "last_record": self.last_record.as_dict() if self.last_record else None,
        }


type HealthListener = Callable[[DeviceHealth, DeliveryRecord], None]


@dataclass
class DeliveryLedger:
    """Ledger of delivery attempts, keyed on the content id we requested."""

    hass: HomeAssistant
    entry: CastConfigEntry
    records: deque[DeliveryRecord] = field(
        default_factory=lambda: deque(maxlen=LEDGER_SIZE)
    )
    devices: dict[UUID, DeviceHealth] = field(default_factory=dict)
    listeners: list[HealthListener] = field(default_factory=list)

    @callback
    def async_add_listener(self, listener: HealthListener) -> CALLBACK_TYPE:
        """Register a callback for every resolved record."""
        self.listeners.append(listener)

        def _remove() -> None:
            self.listeners.remove(listener)

        return _remove

    @callback
    def device(self, uuid: UUID) -> DeviceHealth:
        """Return the health record for a device, creating it on first use."""
        if (health := self.devices.get(uuid)) is None:
            health = DeviceHealth(uuid=uuid)
            self.devices[uuid] = health
        return health

    @callback
    def async_update_identity(
        self,
        uuid: UUID,
        *,
        entity_id: str | None = None,
        name: str | None = None,
        host: str | None = None,
        port: int | None = None,
        seen: bool = False,
    ) -> DeviceHealth:
        """Record what discovery and the entity know about a device."""
        health = self.device(uuid)
        if entity_id is not None:
            health.entity_id = entity_id
        if name is not None:
            health.name = name
        if host is not None:
            health.host = host
        if port is not None:
            health.port = port
        if seen:
            health.last_seen = dt_util.utcnow()
        return health

    def _log_prefix(self, health: DeviceHealth) -> str:
        return (
            f"[{health.entity_id or '?'} {health.name or '?'} uuid={health.uuid} "
            f"host={health.host}:{health.port}]"
        )

    @callback
    def async_begin_request(
        self,
        uuid: UUID,
        content_id: str,
        source: str,
        session_at_request: int | None,
        timeout: float = DELIVERY_TIMEOUT,
    ) -> PendingRequest:
        """Record that a play request is about to be sent."""
        health = self.device(uuid)
        if (old := health.pending) is not None:
            _LOGGER.debug(
                "%s superseding unresolved request content_id=%s after %.1fs with "
                "content_id=%s",
                self._log_prefix(health),
                old.content_id,
                time.monotonic() - old.started,
                content_id,
            )
            self._resolve(
                health,
                DeliveryOutcome.UNKNOWN,
                error="superseded by a newer request before any state transition",
                responded=False,
            )
        pending = PendingRequest(
            content_id=content_id,
            source=source,
            requested_at=dt_util.utcnow(),
            started=time.monotonic(),
            session_at_request=session_at_request,
        )
        health.pending = pending

        @callback
        def _expire(_now: datetime) -> None:
            pending.cancel_timeout = None
            if health.pending is not pending:
                return
            _LOGGER.debug(
                "%s no state transition for content_id=%s within %.0fs "
                "(session_at_request=%s); outcome is unknown, reporting timeout",
                self._log_prefix(health),
                content_id,
                timeout,
                session_at_request,
            )
            self._resolve(
                health,
                DeliveryOutcome.TIMEOUT,
                error=f"no BUFFERING, PLAYING, or ERROR status within {timeout:.0f}s",
                responded=False,
            )

        pending.cancel_timeout = async_call_later(self.hass, timeout, _expire)
        _LOGGER.debug(
            "%s request begun source=%s content_id=%s session_at_request=%s timeout=%.0fs",
            self._log_prefix(health),
            source,
            content_id,
            session_at_request,
            timeout,
        )
        return pending

    @callback
    def async_media_status(
        self,
        uuid: UUID,
        content_id: str | None,
        player_state: str | None,
        idle_reason: str | None,
        media_session_id: int | None,
        player_is_idle: bool,
    ) -> None:
        """Apply a media status callback to the pending request, if any."""
        health = self.device(uuid)
        pending = health.pending
        prefix = self._log_prefix(health)
        observed = {
            "content_id": content_id,
            "player_state": player_state,
            "idle_reason": idle_reason,
            "media_session_id": media_session_id,
        }

        if player_is_idle and idle_reason == IDLE_REASON_ERROR:
            if pending is not None and content_id not in (None, pending.content_id):
                _LOGGER.debug(
                    "%s ERROR status content_id=%s does not match pending content_id=%s; "
                    "recording as an observed failure, request stays pending",
                    prefix,
                    content_id,
                    pending.content_id,
                )
                self._record_observation(health, content_id, observed)
                return
            self._resolve(
                health,
                DeliveryOutcome.FETCH_FAILED,
                error="device reported idleReason=ERROR; it could not fetch the media",
                responded=True,
                observed=observed,
                unsolicited_content_id=content_id if pending is None else None,
            )
            return

        if pending is None:
            return

        if content_id != pending.content_id:
            _LOGGER.debug(
                "%s ignored status (content_id mismatch): requested=%s reported=%s state=%s",
                prefix,
                pending.content_id,
                content_id,
                player_state,
            )
            return

        if player_state not in (MEDIA_PLAYER_STATE_BUFFERING, MEDIA_PLAYER_STATE_PLAYING):
            _LOGGER.debug(
                "%s ignored status (state %s is not BUFFERING or PLAYING) for content_id=%s",
                prefix,
                player_state,
                content_id,
            )
            return

        if (
            pending.session_at_request is not None
            and media_session_id == pending.session_at_request
        ):
            _LOGGER.debug(
                "%s ignored status (media_session_id %s unchanged since the request, "
                "stale metadata is not confirmation) for content_id=%s",
                prefix,
                media_session_id,
                content_id,
            )
            return

        self._resolve(
            health, DeliveryOutcome.OK, error=None, responded=True, observed=observed
        )

    @callback
    def async_load_media_failed(
        self, uuid: UUID, queue_item_id: int | None, error_code: int | None
    ) -> None:
        """Apply a LOAD_FAILED callback to the pending request."""
        health = self.device(uuid)
        message = (
            f"device rejected the load: code {error_code} "
            f"({MEDIA_PLAYER_ERROR_CODES.get(error_code, 'unknown code')}), "
            f"queue item {queue_item_id}"
        )
        if health.pending is None:
            _LOGGER.debug(
                "%s load failed with no pending request: %s", self._log_prefix(health), message
            )
            return
        self._resolve(health, DeliveryOutcome.FETCH_FAILED, error=message, responded=True)

    @callback
    def async_request_failed(self, uuid: UUID, err: BaseException) -> None:
        """Classify an exception raised while sending the play request."""
        health = self.device(uuid)
        cause = err.__cause__ if not isinstance(err, PyChromecastError) else err
        if isinstance(err, TimeoutError):
            outcome = DeliveryOutcome.TIMEOUT
            responded = False
            text = "TimeoutError: the device did not answer before the watchdog expired"
        elif isinstance(cause, RequestTimeout):
            outcome = DeliveryOutcome.TIMEOUT
            responded = False
            text = f"{type(cause).__name__}: {cause}"
        elif isinstance(cause, (NotConnected, ChromecastConnectionError, RequestFailed)):
            outcome = DeliveryOutcome.UNREACHABLE
            responded = False
            text = f"{type(cause).__name__}: {cause}"
        else:
            outcome = DeliveryOutcome.FETCH_FAILED
            responded = True
            text = f"{type(cause or err).__name__}: {cause or err}"
        self._resolve(health, outcome, error=text, responded=responded)

    @callback
    def async_record(
        self,
        uuid: UUID,
        outcome: DeliveryOutcome,
        *,
        source: str,
        content_id: str | None = None,
        error: str | None = None,
        responded: bool = False,
    ) -> DeliveryRecord:
        """Record an outcome that did not come from a device callback.

        Used for template errors, skipped probes, and probe watchdogs.
        """
        health = self.device(uuid)
        if health.pending is not None and health.pending.source == source:
            return self._resolve(health, outcome, error=error, responded=responded)
        return self._append(
            health,
            outcome,
            source=source,
            content_id=content_id,
            error=error,
            responded=responded,
            requested_at=None,
            elapsed=None,
            observed={},
        )

    def _record_observation(
        self, health: DeviceHealth, content_id: str | None, observed: dict[str, Any]
    ) -> None:
        self._append(
            health,
            DeliveryOutcome.FETCH_FAILED,
            source="observed",
            content_id=content_id,
            error="device reported idleReason=ERROR for media this integration did not request",
            responded=True,
            requested_at=None,
            elapsed=None,
            observed=observed,
        )

    def _resolve(
        self,
        health: DeviceHealth,
        outcome: DeliveryOutcome,
        *,
        error: str | None,
        responded: bool,
        observed: dict[str, Any] | None = None,
        unsolicited_content_id: str | None = None,
    ) -> DeliveryRecord:
        pending = health.pending
        health.pending = None
        if pending is not None:
            if pending.cancel_timeout is not None:
                pending.cancel_timeout()
                pending.cancel_timeout = None
            source = pending.source
            content_id: str | None = pending.content_id
            requested_at: datetime | None = pending.requested_at
            elapsed: float | None = round(time.monotonic() - pending.started, 3)
        else:
            source = "observed"
            content_id = unsolicited_content_id
            requested_at = None
            elapsed = None
        return self._append(
            health,
            outcome,
            source=source,
            content_id=content_id,
            error=error,
            responded=responded,
            requested_at=requested_at,
            elapsed=elapsed,
            observed=observed or {},
        )

    def _url_source(self, content_id: str | None) -> str | None:
        if not content_id:
            return None
        external_url = internal_url = None
        with suppress(NoURLAvailableError):
            external_url = get_url(self.hass, allow_internal=False)
        with suppress(NoURLAvailableError):
            internal_url = get_url(self.hass, allow_external=False)
        if internal_url and content_id.startswith(internal_url):
            return "internal_url"
        if external_url and content_id.startswith(external_url):
            return "external_url"
        return None

    def _append(
        self,
        health: DeviceHealth,
        outcome: DeliveryOutcome,
        *,
        source: str,
        content_id: str | None,
        error: str | None,
        responded: bool,
        requested_at: datetime | None,
        elapsed: float | None,
        observed: dict[str, Any],
    ) -> DeliveryRecord:
        now = dt_util.utcnow()
        record = DeliveryRecord(
            uuid=health.uuid,
            entity_id=health.entity_id,
            name=health.name,
            source=source,
            outcome=outcome,
            content_id=content_id,
            error=error,
            url_source=self._url_source(content_id),
            responded=responded,
            requested_at=requested_at,
            resolved_at=now,
            elapsed=elapsed,
            player_state=observed.get("player_state"),
            idle_reason=observed.get("idle_reason"),
            media_session_id=observed.get("media_session_id"),
        )
        self.records.append(record)
        health.last_record = record
        if outcome is not DeliveryOutcome.UNKNOWN and outcome is not DeliveryOutcome.SKIPPED_BUSY:
            health.last_outcome = outcome
        if outcome is DeliveryOutcome.OK:
            health.last_success = now
            health.consecutive_failures = 0
            health.consecutive_timeouts = 0
        elif outcome in FAILURE_OUTCOMES:
            health.consecutive_failures += 1
            if outcome is DeliveryOutcome.TIMEOUT:
                health.consecutive_timeouts += 1
            else:
                health.consecutive_timeouts = 0

        level = logging.INFO if outcome is DeliveryOutcome.OK else logging.WARNING
        if outcome in (DeliveryOutcome.UNKNOWN, DeliveryOutcome.SKIPPED_BUSY):
            level = logging.DEBUG
        _LOGGER.log(
            level,
            "%s delivery outcome=%s source=%s content_id=%s url_source=%s responded=%s "
            "elapsed=%s player_state=%s idle_reason=%s media_session_id=%s "
            "consecutive_failures=%d error=%s",
            self._log_prefix(health),
            outcome.value,
            source,
            content_id,
            record.url_source,
            responded,
            elapsed,
            record.player_state,
            record.idle_reason,
            record.media_session_id,
            health.consecutive_failures,
            error,
        )

        self.hass.bus.async_fire(EVENT_DELIVERY_RESULT, record.as_dict())
        async_dispatcher_send(self.hass, SIGNAL_HEALTH_UPDATED, health.uuid)
        for listener in list(self.listeners):
            listener(health, record)
        return record

    @callback
    def async_shutdown(self) -> None:
        """Cancel pending timers."""
        for health in self.devices.values():
            if health.pending is not None and health.pending.cancel_timeout is not None:
                health.pending.cancel_timeout()
                health.pending.cancel_timeout = None
