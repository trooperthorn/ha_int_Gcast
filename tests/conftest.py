"""Test fixtures for the cast integration."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.tts import _get_cache_files
import pychromecast
from pychromecast.controllers import multizone
import pytest


@pytest.fixture
def get_multizone_status_mock():
    """Mock pychromecast dial."""
    mock = MagicMock(spec_set=pychromecast.dial.get_multizone_status)
    mock.return_value.dynamic_groups = []
    return mock


@pytest.fixture
def get_cast_type_mock():
    """Mock pychromecast dial."""
    return MagicMock(spec_set=pychromecast.dial.get_cast_type)


@pytest.fixture
def castbrowser_mock():
    """Mock pychromecast CastBrowser."""
    return MagicMock(spec=pychromecast.discovery.CastBrowser)


@pytest.fixture
def mz_mock():
    """Mock pychromecast MultizoneManager."""
    return MagicMock(spec_set=multizone.MultizoneManager)


@pytest.fixture
def quick_play_mock():
    """Mock pychromecast quick_play."""
    return MagicMock()


@pytest.fixture
def get_chromecast_mock():
    """Mock pychromecast get_chromecast_from_cast_info."""
    return MagicMock()


@pytest.fixture
def ha_controller_mock():
    """Mock HomeAssistantController."""
    with patch(
        "custom_components.cast.media_player.HomeAssistantController",
        MagicMock(),
    ) as ha_controller_mock:
        yield ha_controller_mock


@pytest.fixture(autouse=True)
def cast_mock(
    mz_mock,
    quick_play_mock,
    castbrowser_mock,
    get_cast_type_mock,
    get_chromecast_mock,
    get_multizone_status_mock,
):
    """Mock pychromecast."""
    ignore_cec_orig = list(pychromecast.IGNORE_CEC)

    with (
        patch(
            "custom_components.cast.discovery.pychromecast.discovery.CastBrowser",
            castbrowser_mock,
        ),
        patch(
            "custom_components.cast.helpers.dial.get_cast_type",
            get_cast_type_mock,
        ),
        patch(
            "custom_components.cast.helpers.dial.get_multizone_status",
            get_multizone_status_mock,
        ),
        patch(
            "custom_components.cast.media_player.MultizoneManager",
            return_value=mz_mock,
        ),
        patch(
            "custom_components.cast.media_player.zeroconf.async_get_instance",
            AsyncMock(),
        ),
        patch(
            "custom_components.cast.media_player.quick_play",
            quick_play_mock,
        ),
        patch(
            "custom_components.cast.media_player.pychromecast.get_chromecast_from_cast_info",
            get_chromecast_mock,
        ),
    ):
        yield

    pychromecast.IGNORE_CEC = list(ignore_cec_orig)


pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the custom integration for every test."""


@pytest.fixture(name="mock_tts_get_cache_files")
def mock_tts_get_cache_files_fixture():
    """Mock the list TTS cache function."""
    with patch(
        "homeassistant.components.tts._get_cache_files", return_value={}
    ) as mock_cache_files:
        yield mock_cache_files


@pytest.fixture(name="mock_tts_init_cache_dir")
def mock_tts_init_cache_dir_fixture():
    """Mock the TTS cache dir in memory."""
    with patch(
        "homeassistant.components.tts._init_tts_cache_dir", side_effect=None
    ) as mock_cache_dir:
        yield mock_cache_dir


@pytest.fixture(name="mock_tts_cache_dir")
def mock_tts_cache_dir_fixture(tmp_path, mock_tts_init_cache_dir, mock_tts_get_cache_files):
    """Mock the TTS cache dir with an empty directory."""
    mock_tts_init_cache_dir.return_value = str(tmp_path)
    mock_tts_get_cache_files.side_effect = _get_cache_files
    return tmp_path


@pytest.fixture(autouse=True)
def media_dirs(hass) -> None:
    """Point the local media source at the bundled media fixtures.

    Core's browse tests read tests/testing_config/media, which the harness
    does not ship, so the same three files live under tests/fixtures/media.
    """
    hass.config.media_dirs = {"local": str(Path(__file__).parent / "fixtures" / "media")}
