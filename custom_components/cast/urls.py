"""Per-device base URL overrides.

Home Assistant has one internal_url and one external_url. A speaker that
must fetch from a different address than the rest (a different VLAN, a
reverse proxy, split DNS that the speaker ignores) can be given its own
base URL in the options. Only URLs that point at this Home Assistant
instance are rewritten; a radio stream or any other third-party URL is
left alone.
"""

from __future__ import annotations

from contextlib import suppress
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url, is_hass_url
import yarl

from .const import CONF_URL_OVERRIDES

if TYPE_CHECKING:
    from . import CastConfigEntry

_LOGGER = logging.getLogger(__name__)


def normalize_override(url: str) -> str | None:
    """Return "scheme://host[:port]" for a usable override, else None."""
    with suppress(ValueError, TypeError):
        parsed = yarl.URL(url.strip())
        if (
            parsed.scheme in ("http", "https")
            and parsed.host
            and parsed.path in ("", "/")
            and not parsed.query_string
            and not parsed.fragment
            and not parsed.user
        ):
            return str(parsed.with_path("")).rstrip("/")
    return None


def url_overrides(entry: CastConfigEntry) -> dict[UUID, str]:
    """Read the valid overrides from the entry options."""
    overrides: dict[UUID, str] = {}
    raw = entry.options.get(CONF_URL_OVERRIDES) or {}
    for key, value in raw.items():
        try:
            uuid = UUID(str(key))
        except ValueError:
            _LOGGER.warning("url override ignored: %r is not a device uuid", key)
            continue
        if (base := normalize_override(str(value))) is None:
            _LOGGER.warning(
                "url override ignored for uuid=%s: %r is not a base URL", uuid, value
            )
            continue
        overrides[uuid] = base
    return overrides


def _is_own_url(hass: HomeAssistant, url: str) -> bool:
    """True when the URL points at this instance by any of its known bases."""
    if is_hass_url(hass, url):
        return True
    # is_hass_url only knows a pinned internal_url; an automatic one resolves
    # through get_url, so compare against that as well.
    for kwargs in ({"allow_external": False}, {"allow_internal": False}):
        with suppress(NoURLAvailableError):
            if url.startswith(get_url(hass, **kwargs)):
                return True
    return False


def rewrite_hass_url(hass: HomeAssistant, url: str, base: str) -> str:
    """Point a Home Assistant URL at base; return other URLs unchanged."""
    if not _is_own_url(hass, url):
        return url
    parsed = yarl.URL(url)
    target = yarl.URL(base)
    assert target.host is not None
    return str(
        parsed.with_scheme(target.scheme)
        .with_host(target.host)
        .with_port(target.explicit_port)
    )
