"""Serve the silent probe clip that active reachability probing plays."""

from __future__ import annotations

from http import HTTPStatus
import io
import secrets
from typing import Final
import wave

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

PROBE_PATH: Final = "/api/cast/probe"
PROBE_CONTENT_TYPE: Final = "audio/wav"
DATA_PROBE_TOKEN: HassKey[str] = HassKey("cast_probe_token")


def _silent_wav(seconds: float = 0.25, rate: int = 8000) -> bytes:
    """Return a mono 8-bit PCM WAV of silence."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(1)
        clip.setframerate(rate)
        clip.writeframes(bytes([128]) * int(seconds * rate))
    return buffer.getvalue()


SILENT_CLIP: Final = _silent_wav()


class CastProbeView(HomeAssistantView):
    """Unauthenticated view returning the silent clip for the current token.

    Cast devices cannot present Home Assistant credentials, which is also why
    the TTS proxy is unauthenticated. The token is random per Home Assistant
    start and the payload is a quarter second of silence.
    """

    url = f"{PROBE_PATH}/{{token}}.wav"
    name = "api:cast:probe"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self._hass = hass

    async def get(self, request: web.Request, token: str) -> web.Response:
        """Return the clip when the token matches."""
        if not secrets.compare_digest(token, self._hass.data.get(DATA_PROBE_TOKEN, "")):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        return web.Response(
            body=SILENT_CLIP,
            content_type=PROBE_CONTENT_TYPE,
            headers={"Cache-Control": "no-store"},
        )


@callback
def async_setup_probe_view(hass: HomeAssistant) -> str:
    """Register the probe view once and return the relative probe URL."""
    if DATA_PROBE_TOKEN not in hass.data:
        hass.data[DATA_PROBE_TOKEN] = secrets.token_urlsafe(16)
        hass.http.register_view(CastProbeView(hass))
    return f"{PROBE_PATH}/{hass.data[DATA_PROBE_TOKEN]}.wav"
