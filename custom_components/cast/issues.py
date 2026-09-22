"""Repair issues and stale device tracking (WP4).

Every issue names the device and the next action, and every issue deletes
itself when its condition clears; see DESIGN.md section 11.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STALE_DEVICE_DAYS
from .health import DeliveryOutcome, DeliveryRecord, DeviceHealth

if TYPE_CHECKING:
    from . import CastConfigEntry
    from .topology import TopologyTracker

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.health"
SAVE_DELAY = 30

ISSUE_FETCH_FAILED = "tts_fetch_failed"
ISSUE_MULTIHOMED = "internal_url_automatic_multihomed"
ISSUE_GROUP_SPANS = "cast_group_spans_subnets"
ISSUE_STALE_DEVICE = "stale_cast_device"
ISSUE_TEMPLATE_ERROR = "tts_template_error"
ISSUE_UNREACHABLE = "cast_device_unreachable"
FETCH_FAILURES_BEFORE_ISSUE = 2


@dataclass
class StaleCandidate:
    """A registry device with no discovery response for too long."""

    device_id: str
    name: str
    uuid: str | None
    last_seen: datetime | None
    tracked_since: datetime


@dataclass
class RepairManager:
    """Own every repair issue the integration raises."""

    hass: HomeAssistant
    entry: CastConfigEntry
    store: Store[dict[str, Any]] = field(init=False)
    last_seen: dict[str, datetime] = field(default_factory=dict)
    tracked_since: dict[str, datetime] = field(default_factory=dict)
    consecutive_fetch_failures: dict[UUID, int] = field(default_factory=dict)
    consecutive_unreachable: dict[UUID, int] = field(default_factory=dict)
    stale: dict[str, StaleCandidate] = field(default_factory=dict)
    _unsub: CALLBACK_TYPE | None = None

    def __post_init__(self) -> None:
        """Create the store."""
        self.store = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_load(self) -> None:
        """Load persisted last-seen timestamps and attach to the ledger."""
        data = await self.store.async_load() or {}
        for key, target in (("last_seen", self.last_seen), ("tracked_since", self.tracked_since)):
            for uuid, stamp in (data.get(key) or {}).items():
                if (parsed := dt_util.parse_datetime(stamp)) is not None:
                    target[uuid] = parsed
        ledger = self.entry.runtime_data.get_ledger(self.hass, self.entry)
        for uuid, stamp in self.last_seen.items():
            try:
                ledger.device(UUID(uuid)).last_seen = stamp
            except ValueError:
                continue
        self._unsub = ledger.async_add_listener(self.async_on_record)
        _LOGGER.debug(
            "repair manager loaded last_seen for %d devices, tracking since for %d",
            len(self.last_seen),
            len(self.tracked_since),
        )

    @callback
    def async_shutdown(self) -> None:
        """Detach from the ledger."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def async_flush(self) -> None:
        """Write the last-seen data now instead of after the save delay."""
        await self.store.async_save(self._data_to_save())

    def _schedule_save(self) -> None:
        self.store.async_delay_save(self._data_to_save, SAVE_DELAY)

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "last_seen": {uuid: stamp.isoformat() for uuid, stamp in self.last_seen.items()},
            "tracked_since": {
                uuid: stamp.isoformat() for uuid, stamp in self.tracked_since.items()
            },
        }

    @callback
    def async_device_seen(self, uuid: UUID) -> None:
        """Record a discovery response and clear a stale issue if one exists."""
        key = str(uuid)
        self.last_seen[key] = dt_util.utcnow()
        self._schedule_save()
        for device_id, candidate in list(self.stale.items()):
            if candidate.uuid == key:
                self._delete(f"{ISSUE_STALE_DEVICE}.{device_id}")
                del self.stale[device_id]

    @callback
    def async_on_record(self, health: DeviceHealth, record: DeliveryRecord) -> None:
        """Raise or clear the fetch-failure issue from delivery outcomes."""
        uuid = health.uuid
        if record.outcome is DeliveryOutcome.FETCH_FAILED:
            count = self.consecutive_fetch_failures.get(uuid, 0) + 1
            self.consecutive_fetch_failures[uuid] = count
            if count >= FETCH_FAILURES_BEFORE_ISSUE:
                self._create(
                    f"{ISSUE_FETCH_FAILED}.{uuid}",
                    ir.IssueSeverity.ERROR,
                    ISSUE_FETCH_FAILED,
                    {
                        "name": health.name or str(uuid),
                        "entity_id": health.entity_id or "",
                        "host": health.host or "unknown",
                        "url_source": record.url_source or "a URL outside Home Assistant",
                        "count": str(count),
                        "error": record.error or "",
                    },
                )
        elif record.outcome is DeliveryOutcome.UNREACHABLE:
            count = self.consecutive_unreachable.get(uuid, 0) + 1
            self.consecutive_unreachable[uuid] = count
            if count >= FETCH_FAILURES_BEFORE_ISSUE:
                self._create(
                    f"{ISSUE_UNREACHABLE}.{uuid}",
                    ir.IssueSeverity.ERROR,
                    ISSUE_UNREACHABLE,
                    {
                        "name": health.name or str(uuid),
                        "entity_id": health.entity_id or "",
                        "host": health.host or "unknown",
                        "count": str(count),
                        "error": record.error or "",
                    },
                )
        elif record.outcome is DeliveryOutcome.OK:
            self.consecutive_fetch_failures[uuid] = 0
            self.consecutive_unreachable[uuid] = 0
            self._delete(f"{ISSUE_FETCH_FAILED}.{uuid}")
            self._delete(f"{ISSUE_UNREACHABLE}.{uuid}")

    @callback
    def async_template_error(
        self, entity_id: str, template: str, error: str, *, resolved: bool = False
    ) -> str:
        """Raise or clear a template error issue keyed on the template text."""
        digest = hashlib.sha1(template.encode()).hexdigest()[:12]
        issue_id = f"{ISSUE_TEMPLATE_ERROR}.{digest}"
        if resolved:
            self._delete(issue_id)
        else:
            self._create(
                issue_id,
                ir.IssueSeverity.ERROR,
                ISSUE_TEMPLATE_ERROR,
                {
                    "entity_id": entity_id,
                    "template": template if len(template) <= 200 else template[:197] + "...",
                    "error": error,
                },
            )
        return issue_id

    @callback
    def async_check_topology(self, topology: TopologyTracker) -> None:
        """Raise or clear the multihomed and subnet-span issues."""
        if topology.multihomed and topology.internal_url_automatic:
            self._create(
                ISSUE_MULTIHOMED,
                ir.IssueSeverity.WARNING,
                ISSUE_MULTIHOMED,
                {
                    "host": topology.internal_host or "unknown",
                    "adapters": ", ".join(str(net) for net in topology.adapter_networks),
                },
            )
        else:
            self._delete(ISSUE_MULTIHOMED)

        for uuid, group in topology.groups.items():
            issue_id = f"{ISSUE_GROUP_SPANS}.{uuid}"
            if group.members_span_subnets:
                self._create(
                    issue_id,
                    ir.IssueSeverity.WARNING,
                    ISSUE_GROUP_SPANS,
                    {
                        "name": group.name or str(uuid),
                        "leader_ip": group.leader_ip or "unknown",
                        "subnets": ", ".join(sorted({s for s in group.subnets.values() if s})),
                    },
                )
            else:
                self._delete(issue_id)

    @callback
    def async_check_stale(self, discovered: set[UUID]) -> list[StaleCandidate]:
        """Raise a fixable issue for registry devices unseen for too long."""
        now = dt_util.utcnow()
        registry = dr.async_get(self.hass)
        threshold = now - timedelta(days=STALE_DEVICE_DAYS)
        seen_strs = {str(uuid) for uuid in discovered}
        current: dict[str, StaleCandidate] = {}
        for device in dr.async_entries_for_config_entry(registry, self.entry.entry_id):
            uuid_hex = next(
                (ident for domain, ident in device.identifiers if domain == DOMAIN), None
            )
            uuid_str: str | None = None
            if uuid_hex is not None:
                try:
                    uuid_str = str(UUID(uuid_hex))
                except ValueError:
                    uuid_str = None
            if uuid_str in seen_strs:
                continue
            key = uuid_str or device.id
            tracked_since = self.tracked_since.setdefault(key, now)
            last_seen = self.last_seen.get(key) if uuid_str else None
            reference = last_seen or tracked_since
            if reference > threshold:
                continue
            current[device.id] = StaleCandidate(
                device_id=device.id,
                name=device.name_by_user or device.name or device.id,
                uuid=uuid_str,
                last_seen=last_seen,
                tracked_since=tracked_since,
            )
        self._schedule_save()

        for device_id in list(self.stale):
            if device_id not in current:
                self._delete(f"{ISSUE_STALE_DEVICE}.{device_id}")
        for device_id, candidate in current.items():
            self._create(
                f"{ISSUE_STALE_DEVICE}.{device_id}",
                ir.IssueSeverity.WARNING,
                ISSUE_STALE_DEVICE,
                {
                    "name": candidate.name,
                    "days": str(STALE_DEVICE_DAYS),
                    "last_seen": (
                        candidate.last_seen.isoformat(timespec="minutes")
                        if candidate.last_seen
                        else f"never since {candidate.tracked_since.isoformat(timespec='minutes')}"
                    ),
                },
                is_fixable=True,
                data={"device_id": device_id},
            )
        self.stale = current
        return list(current.values())

    def _create(
        self,
        issue_id: str,
        severity: ir.IssueSeverity,
        translation_key: str,
        placeholders: dict[str, str],
        *,
        is_fixable: bool = False,
        data: dict[str, str | int | float | None] | None = None,
    ) -> None:
        existing = ir.async_get(self.hass).async_get_issue(DOMAIN, issue_id)
        if existing is None:
            _LOGGER.warning(
                "repair issue raised id=%s severity=%s %s",
                issue_id,
                severity.value,
                " ".join(f"{key}={value!r}" for key, value in placeholders.items()),
            )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=is_fixable,
            severity=severity,
            translation_key=translation_key,
            translation_placeholders=placeholders,
            data=data,
        )

    def _delete(self, issue_id: str) -> None:
        if ir.async_get(self.hass).async_get_issue(DOMAIN, issue_id) is None:
            return
        _LOGGER.info("repair issue cleared id=%s (condition no longer holds)", issue_id)
        ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def as_dict(self) -> dict[str, Any]:
        """Serialize for diagnostics."""
        registry = ir.async_get(self.hass)
        return {
            "active_issues": sorted(
                issue_id for domain, issue_id in registry.issues if domain == DOMAIN
            ),
            "stale_candidates": [
                {
                    "device_id": c.device_id,
                    "name": c.name,
                    "uuid": c.uuid,
                    "last_seen": c.last_seen.isoformat() if c.last_seen else None,
                    "tracked_since": c.tracked_since.isoformat(),
                }
                for c in self.stale.values()
            ],
            "consecutive_fetch_failures": {
                str(uuid): count for uuid, count in self.consecutive_fetch_failures.items()
            },
            "consecutive_unreachable": {
                str(uuid): count for uuid, count in self.consecutive_unreachable.items()
            },
        }
