"""Tests for the Cast config flow."""

from typing import Any
from unittest.mock import ANY, patch

from homeassistant import config_entries
from homeassistant.components import cast
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    get_schema_suggested_value,
)

from custom_components.cast import DOMAIN
from custom_components.cast.coordinator import probe_options
from custom_components.cast.home_assistant_cast import CAST_USER_NAME


def _get_schema_suggested_values(data_schema, keys: list[str]) -> dict[str, Any]:
    """Get suggested values from a data schema."""
    suggested_values = {}
    for key in keys:
        if (
            suggested_value := get_schema_suggested_value(data_schema, key)
        ) is not None:
            suggested_values[key] = suggested_value
    return suggested_values


async def test_creating_entry_sets_up_media_player(hass: HomeAssistant) -> None:
    """Test setting up Cast loads the media player."""
    with (
        patch(
            "custom_components.cast.media_player.async_setup_entry",
            return_value=True,
        ) as mock_setup,
        patch("pychromecast.discovery.discover_chromecasts", return_value=(True, None)),
        patch(
            "pychromecast.discovery.stop_discovery",
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            cast.DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        # Confirmation form
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY

        await hass.async_block_till_done()

    assert len(mock_setup.mock_calls) == 1


@pytest.mark.parametrize(
    "source",
    [
        config_entries.SOURCE_USER,
        config_entries.SOURCE_ZEROCONF,
    ],
)
async def test_single_instance(hass: HomeAssistant, source) -> None:
    """Test we only allow a single config flow."""
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_user_setup(hass: HomeAssistant) -> None:
    """Test we can finish a config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    users = await hass.auth.async_get_users()
    assert next(user for user in users if user.name == CAST_USER_NAME)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data == {
        "ignore_cec": [],
        "known_hosts": [],
        "uuid": [],
        "user_id": users[0].id,  # Home Assistant cast user
    }


async def test_user_setup_options(hass: HomeAssistant) -> None:
    """Test we can finish a config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"known_hosts": ["192.168.0.1", "", " ", "192.168.0.2 "]}
    )

    users = await hass.auth.async_get_users()
    assert next(user for user in users if user.name == CAST_USER_NAME)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data == {
        "ignore_cec": [],
        "known_hosts": ["192.168.0.1", "192.168.0.2"],
        "uuid": [],
        "user_id": users[0].id,  # Home Assistant cast user
    }


async def test_zeroconf_setup(hass: HomeAssistant) -> None:
    """Test we can finish a config flow through zeroconf."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    users = await hass.auth.async_get_users()
    assert next(user for user in users if user.name == CAST_USER_NAME)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data == {
        "ignore_cec": [],
        "known_hosts": [],
        "uuid": [],
        "user_id": users[0].id,  # Home Assistant cast user
    }


async def test_zeroconf_setup_onboarding(hass: HomeAssistant) -> None:
    """Test we automatically finish a config flow through zeroconf during onboarding."""
    with patch(
        "homeassistant.components.onboarding.async_is_onboarded", return_value=False
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}
        )

    users = await hass.auth.async_get_users()
    assert next(user for user in users if user.name == CAST_USER_NAME)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data == {
        "ignore_cec": [],
        "known_hosts": [],
        "uuid": [],
        "user_id": users[0].id,  # Home Assistant cast user
    }


@pytest.mark.parametrize(
    ("initial", "expected_suggested_values", "user_input", "updated"),
    [
        (
            {},
            {},
            {"more_options": {}, "health": {}},
            {"ignore_cec": [], "known_hosts": [], "user_id": ANY, "uuid": []},
        ),
        (
            {"ignore_cec": [], "known_hosts": [], "uuid": []},
            {"ignore_cec": [], "known_hosts": [], "uuid": []},
            {"more_options": {}, "health": {}},
            {"ignore_cec": [], "known_hosts": [], "user_id": ANY, "uuid": []},
        ),
        (
            {
                "ignore_cec": ["cast1", "cast2"],
                "known_hosts": ["192.168.0.10", "192.168.0.11"],
                "uuid": ["bla", "blu"],
            },
            {
                "ignore_cec": ["cast1", "cast2"],
                "known_hosts": ["192.168.0.10", "192.168.0.11"],
                "uuid": ["bla", "blu"],
            },
            {
                "known_hosts": ["192.168.0.1", " ", "  192.168.0.2 "],
                "more_options": {
                    "ignore_cec": ["other_cast", " ", "  some_cast "],
                    "uuid": ["foo", " ", "  bar "],
                },
                "health": {},
            },
            {
                "ignore_cec": ["other_cast", "some_cast"],
                "known_hosts": ["192.168.0.1", "192.168.0.2"],
                "user_id": ANY,
                "uuid": ["foo", "bar"],
            },
        ),
        # Implicit clearing of the lists when not passing values
        (
            {
                "ignore_cec": ["cast1", "cast2"],
                "known_hosts": ["192.168.0.10", "192.168.0.11"],
                "uuid": ["bla", "blu"],
            },
            {
                "ignore_cec": ["cast1", "cast2"],
                "known_hosts": ["192.168.0.10", "192.168.0.11"],
                "uuid": ["bla", "blu"],
            },
            {"more_options": {}, "health": {}},
            {"ignore_cec": [], "known_hosts": [], "user_id": ANY, "uuid": []},
        ),
        # Explicit clearing of the lists
        (
            {
                "ignore_cec": ["cast1", "cast2"],
                "known_hosts": ["192.168.0.10", "192.168.0.11"],
                "uuid": ["bla", "blu"],
            },
            {
                "ignore_cec": ["cast1", "cast2"],
                "known_hosts": ["192.168.0.10", "192.168.0.11"],
                "uuid": ["bla", "blu"],
            },
            {
                "known_hosts": [],
                "more_options": {"ignore_cec": [], "uuid": []},
                "health": {},
            },
            {"ignore_cec": [], "known_hosts": [], "user_id": ANY, "uuid": []},
        ),
    ],
)
async def test_option_flow(
    hass: HomeAssistant,
    initial: dict[str, Any],
    expected_suggested_values: dict[str, Any],
    user_input: dict[str, Any],
    updated: dict[str, Any],
) -> None:
    """Test config flow options."""
    basic_parameters = ["known_hosts"]
    extra_parameters = ["ignore_cec", "uuid"]

    config_entry = MockConfigEntry(domain=DOMAIN, data=initial)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Check the data schema
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    data_schema = result["data_schema"].schema
    assert set(data_schema) == {"known_hosts", "more_options", "health"}
    more_options_schema = data_schema["more_options"].schema.schema
    assert set(more_options_schema) == {"ignore_cec", "uuid"}

    # Check suggested values
    suggested_values = _get_schema_suggested_values(data_schema, basic_parameters)
    suggested_values |= _get_schema_suggested_values(
        more_options_schema, extra_parameters
    )
    assert suggested_values == expected_suggested_values

    # Reconfigure
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=user_input,
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "probe_enabled": True,
        "probe_interval": 300,
        "group_probe_enabled": True,
        "probe_video_devices": False,
    }
    assert config_entry.data == updated


async def test_known_hosts(hass: HomeAssistant, castbrowser_mock) -> None:
    """Test known hosts is passed to pychromecast."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"known_hosts": ["192.168.0.1", "192.168.0.2"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    config_entry = hass.config_entries.async_entries("cast")[0]

    assert castbrowser_mock.return_value.start_discovery.call_count == 1
    castbrowser_mock.assert_called_once_with(ANY, ANY, ["192.168.0.1", "192.168.0.2"])
    castbrowser_mock.reset_mock()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "known_hosts": ["192.168.0.11", "192.168.0.12"],
            "more_options": {},
        },
    )

    await hass.async_block_till_done(wait_background_tasks=True)

    castbrowser_mock.return_value.start_discovery.assert_not_called()
    castbrowser_mock.assert_not_called()
    castbrowser_mock.return_value.host_browser.update_hosts.assert_called_once_with(
        ["192.168.0.11", "192.168.0.12"]
    )


async def test_option_flow_health_shows_what_is_running(
    hass: HomeAssistant,
) -> None:
    """An entry with nothing stored must show the defaults that are in effect.

    Regression: the form filtered its suggested values to the keys already
    present in options, so an entry that had never saved them drew every
    checkbox unchecked while probe_options() fell back to the defaults and
    probing ran. The form said off, the runtime said on.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    health_schema = result["data_schema"].schema["health"]
    suggested = _get_schema_suggested_values(
        health_schema.schema.schema,
        [
            "probe_enabled",
            "probe_interval",
            "group_probe_enabled",
            "probe_video_devices",
        ],
    )
    running = probe_options(config_entry)

    assert suggested["probe_enabled"] == running.enabled
    assert suggested["probe_interval"] == running.interval
    assert suggested["group_probe_enabled"] == running.groups
    assert suggested["probe_video_devices"] == running.video


async def test_option_flow_health_section(hass: HomeAssistant) -> None:
    """The delivery health options are stored on the entry and re-suggested."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    health_schema = result["data_schema"].schema["health"].schema.schema
    assert set(health_schema) == {
        "probe_enabled",
        "probe_interval",
        "group_probe_enabled",
        "probe_video_devices",
        "edit_url_overrides",
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "more_options": {},
            "health": {
                "probe_enabled": False,
                "probe_interval": 120,
                "group_probe_enabled": False,
                "probe_video_devices": True,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "probe_enabled": False,
        "probe_interval": 120,
        "group_probe_enabled": False,
        "probe_video_devices": True,
    }

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    health_schema = result["data_schema"].schema["health"].schema.schema
    assert _get_schema_suggested_values(health_schema, ["probe_interval"]) == {
        "probe_interval": 120
    }

    # The interval floor is enforced by the schema.
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"more_options": {}, "health": {"probe_interval": 10}}
        )
