"""Tests for the probe clip view."""

from http import HTTPStatus

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.cast.probe import (
    DATA_PROBE_TOKEN,
    SILENT_CLIP,
    async_setup_probe_view,
)


async def test_probe_view_serves_silence(
    hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """The clip is served without authentication for the current token only."""
    assert await async_setup_component(hass, "http", {})
    url = async_setup_probe_view(hass)
    assert url == async_setup_probe_view(hass)
    assert url.startswith("/api/cast/probe/") and url.endswith(".wav")

    client = await hass_client_no_auth()
    resp = await client.get(url)
    assert resp.status == HTTPStatus.OK
    assert resp.content_type == "audio/wav"
    assert resp.headers["Cache-Control"] == "no-store"
    body = await resp.read()
    assert body == SILENT_CLIP
    assert body[:4] == b"RIFF" and b"WAVE" in body[:12]
    assert len(body) < 4096

    resp = await client.get("/api/cast/probe/not-the-token.wav")
    assert resp.status == HTTPStatus.NOT_FOUND
    assert hass.data[DATA_PROBE_TOKEN] in url
