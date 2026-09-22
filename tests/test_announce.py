"""Tests for the monitored cast.announce action (WP4)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.media_source import PlayMedia
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.cast.const import DOMAIN, EVENT_DELIVERY_RESULT
from custom_components.cast.health import DeliveryOutcome
from tests.test_health import ENTITY_ID, OUTCOME, _setup, _status

TTS_URL = "/api/tts_proxy/announce.mp3"


@pytest.fixture(autouse=True)
async def mock_tts_engine() -> AsyncGenerator[MagicMock]:
    """Stand in for a TTS engine: the demo platform needs the conversation stack.

    The media source id and its resolution are patched at the points the
    entity calls them, so the announce path up to quick_play is the real one.
    """

    def generate(hass, message, engine=None, language=None, options=None, cache=None):
        return f"media-source://tts/mock?message={message}"

    with (
        patch(
            "custom_components.cast.media_player.tts.generate_media_source_id",
            side_effect=generate,
        ) as generate_mock,
        patch(
            "custom_components.cast.media_player.media_source.is_media_source_id",
            return_value=True,
        ),
        patch(
            "custom_components.cast.media_player.media_source.async_resolve_media",
            AsyncMock(return_value=PlayMedia(TTS_URL, "audio/mpeg")),
        ),
    ):
        yield generate_mock


async def _setup_with_tts(hass: HomeAssistant):
    return await _setup(hass)


async def test_announce_tracks_delivery(
    hass: HomeAssistant, quick_play_mock, mock_tts_engine: MagicMock
) -> None:
    """A rendered announcement is played through TTS and tracked as source announce."""
    _, media_status_cb = await _setup_with_tts(hass)
    hass.states.async_set("sensor.minutes", "12")
    events = async_capture_events(hass, EVENT_DELIVERY_RESULT)

    await hass.services.async_call(
        DOMAIN,
        "announce",
        {
            "entity_id": ENTITY_ID,
            "message": "Open for {{ states('sensor.minutes') | int }} minutes",
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    quick_play_mock.assert_called_once()
    _, app_name, data = quick_play_mock.call_args[0]
    assert app_name == "default_media_receiver"
    assert data["media_id"] == f"http://example.local:8123{TTS_URL}"
    assert mock_tts_engine.call_args.kwargs["message"] == "Open for 12 minutes"

    media_status_cb(_status(content_id=data["media_id"], player_state="PLAYING", media_session_id=4))
    await hass.async_block_till_done()
    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.OK
    assert outcome.attributes["source"] == "announce"
    assert events[-1].data["source"] == "announce"


async def test_announce_template_error(hass: HomeAssistant, quick_play_mock) -> None:
    """A template that fails to render becomes template_error plus a repair issue."""
    await _setup_with_tts(hass)
    hass.states.async_set("sensor.minutes", "unknown")
    events = async_capture_events(hass, EVENT_DELIVERY_RESULT)
    template = "Open for {{ states('sensor.minutes') | int }} minutes"

    with pytest.raises(ServiceValidationError, match="was not sent"):
        await hass.services.async_call(
            DOMAIN,
            "announce",
            {"entity_id": ENTITY_ID, "message": template},
            blocking=True,
        )
    await hass.async_block_till_done()
    quick_play_mock.assert_not_called()
    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.TEMPLATE_ERROR
    assert outcome.attributes["source"] == "announce"
    assert "int" in outcome.attributes["error"]
    assert events[-1].data["outcome"] == "template_error"

    registry = ir.async_get(hass)
    issues = [i for (d, i) in registry.issues if d == DOMAIN and i.startswith("tts_template_error")]
    assert len(issues) == 1
    issue = registry.async_get_issue(DOMAIN, issues[0])
    assert issue.translation_placeholders["entity_id"] == ENTITY_ID
    assert template in issue.translation_placeholders["template"]

    # The same template rendering later clears the issue.
    hass.states.async_set("sensor.minutes", "3")
    await hass.services.async_call(
        DOMAIN, "announce", {"entity_id": ENTITY_ID, "message": template}, blocking=True
    )
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issues[0]) is None


async def test_announce_empty_message(hass: HomeAssistant, quick_play_mock) -> None:
    """A template rendering to nothing is a template_error, not a silent no-op."""
    await _setup_with_tts(hass)
    with pytest.raises(ServiceValidationError, match="empty"):
        await hass.services.async_call(
            DOMAIN,
            "announce",
            {"entity_id": ENTITY_ID, "message": "{{ '' }}"},
            blocking=True,
        )
    quick_play_mock.assert_not_called()
    assert hass.states.get(OUTCOME).state == DeliveryOutcome.TEMPLATE_ERROR


async def test_announce_without_tts_engine(
    hass: HomeAssistant, quick_play_mock, mock_tts_engine: MagicMock
) -> None:
    """No TTS engine is reported as a template_error with the reason, then raised."""
    await _setup(hass)
    mock_tts_engine.side_effect = HomeAssistantError("Invalid TTS provider selected")
    with pytest.raises(HomeAssistantError, match="Invalid TTS provider"):
        await hass.services.async_call(
            DOMAIN, "announce", {"entity_id": ENTITY_ID, "message": "hello"}, blocking=True
        )
    outcome = hass.states.get(OUTCOME)
    assert outcome.state == DeliveryOutcome.TEMPLATE_ERROR
    assert "TTS engine unavailable" in outcome.attributes["error"]
    assert isinstance(quick_play_mock, MagicMock)
