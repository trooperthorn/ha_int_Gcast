"""Tests for setting up the forked cast integration."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cast.const import DOMAIN


async def test_integration_loads_from_custom_components(hass: HomeAssistant) -> None:
    """The fork loads under custom_components and shadows the core domain."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"ignore_cec": [], "known_hosts": [], "uuid": []}
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.cast.media_player.async_setup_entry", return_value=True
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    integration = await async_get_integration(hass, DOMAIN)
    assert not integration.is_built_in
    assert "custom_components" in str(integration.file_path)
