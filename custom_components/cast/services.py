"""The monitored announce action."""

from __future__ import annotations

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import VolDictType
import voluptuous as vol

from .const import DOMAIN

SERVICE_ANNOUNCE = "announce"
ATTR_MESSAGE = "message"
ATTR_ENGINE = "engine"
ATTR_LANGUAGE = "language"
ATTR_CACHE = "cache"
ATTR_OPTIONS = "options"

ANNOUNCE_SCHEMA: VolDictType = {
    vol.Required(ATTR_MESSAGE): cv.string,
    vol.Optional(ATTR_ENGINE): cv.string,
    vol.Optional(ATTR_LANGUAGE): cv.string,
    vol.Optional(ATTR_CACHE): cv.boolean,
    vol.Optional(ATTR_OPTIONS): dict,
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
