"""The monitored announce action."""

from __future__ import annotations

from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import VolDictType
import probatio

from .const import DOMAIN

SERVICE_ANNOUNCE = "announce"
ATTR_MESSAGE = "message"
ATTR_ENGINE = "engine"
ATTR_LANGUAGE = "language"
ATTR_CACHE = "cache"
ATTR_OPTIONS = "options"

ANNOUNCE_SCHEMA: VolDictType = {
    probatio.Required(ATTR_MESSAGE): cv.string,
    probatio.Optional(ATTR_ENGINE): cv.string,
    probatio.Optional(ATTR_LANGUAGE): cv.string,
    probatio.Optional(ATTR_CACHE): cv.boolean,
    probatio.Optional(ATTR_OPTIONS): dict,
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the announce action on this integration's media players."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_ANNOUNCE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        func="async_announce",
        schema=ANNOUNCE_SCHEMA,
    )
