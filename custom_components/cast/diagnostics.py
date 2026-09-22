"""Diagnostics: answer "is TTS working, and if not, why" without a log."""

from __future__ import annotations

from contextlib import suppress
from ipaddress import IPv4Network
from typing import Any
from urllib.parse import urlparse

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.network import NoURLAvailableError, get_url

from . import CastConfigEntry
from .const import DOMAIN
from .topology import _as_ipv4

TO_REDACT = {"external_url", "external_host", "user_id", "refresh_token"}


def _adapter_for(host: str | None, networks: list[IPv4Network]) -> str | None:
    ip = _as_ipv4(host)
    if ip is None:
        return None
    return next((str(net) for net in networks if ip in net), None)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CastConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    runtime = entry.runtime_data
    ledger = runtime.get_ledger(hass, entry)
    topology = runtime.topology
    if topology is not None:
        await topology.async_refresh()
    networks = topology.adapter_networks if topology else []

    internal_url = external_url = None
    with suppress(NoURLAvailableError):
        internal_url = get_url(hass, allow_external=False)
    with suppress(NoURLAvailableError):
        external_url = get_url(hass, allow_internal=False)
    internal_host = urlparse(internal_url).hostname if internal_url else None
    external_host = urlparse(external_url).hostname if external_url else None

    discovered = topology.infos if topology else {}
    devices = []
    for uuid, info in discovered.items():
        health = ledger.device(uuid)
        devices.append(
            {
                **health.as_dict(),
                "model": info.cast_info.model_name,
                "manufacturer": info.cast_info.manufacturer,
                "cast_type": info.cast_info.cast_type,
                "is_audio_group": info.is_audio_group,
                "is_dynamic_group": info.is_dynamic_group,
                "subnet": _adapter_for(info.cast_info.host, networks),
            }
        )

    registry = dr.async_get(hass)
    discovered_hex = {str(uuid).replace("-", "") for uuid in discovered}
    registry_without_discovery = [
        {
            "device_id": device.id,
            "name": device.name_by_user or device.name,
            "identifiers": sorted(f"{d}:{i}" for d, i in device.identifiers),
            "disabled": device.disabled,
        }
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if not any(d == DOMAIN and i in discovered_hex for d, i in device.identifiers)
    ]

    coordinator = runtime.coordinator
    data: dict[str, Any] = {
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
            "version": entry.version,
        },
        "urls": {
            "internal_url": internal_url,
            "internal_url_pinned": hass.config.internal_url is not None,
            "internal_url_adapter": _adapter_for(internal_host, networks),
            "external_url": external_url,
            "external_host": external_host,
            "external_url_pinned": hass.config.external_url is not None,
        },
        "network": topology.as_dict() if topology else None,
        "devices": devices,
        "groups": topology.as_dict()["groups"] if topology else [],
        "ledger": [record.as_dict() for record in ledger.records],
        "registry_without_discovery": registry_without_discovery,
        "probe": {
            "options": (
                {
                    "enabled": coordinator.options.enabled,
                    "interval": coordinator.options.interval,
                    "groups": coordinator.options.groups,
                    "video": coordinator.options.video,
                }
                if coordinator
                else None
            ),
            "last_update_success": coordinator.last_update_success if coordinator else None,
            "decisions": (
                {
                    str(uuid): {
                        "checked_at": result.checked_at.isoformat(),
                        "decision": result.decision,
                        "outcome": result.outcome.value if result.outcome else None,
                    }
                    for uuid, result in (coordinator.data or {}).items()
                }
                if coordinator
                else {}
            ),
        },
        "repairs": runtime.repairs.as_dict() if runtime.repairs else None,
    }
    return async_redact_data(data, TO_REDACT)
