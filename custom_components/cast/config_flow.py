"""Config flow for Cast."""

from typing import TYPE_CHECKING, Any, override

from homeassistant.components import onboarding
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_DEVICE, CONF_URL, CONF_UUID
from homeassistant.core import callback
from homeassistant.data_entry_flow import SectionConfig, section
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from .const import (
    CONF_GROUP_PROBE_ENABLED,
    CONF_IGNORE_CEC,
    CONF_KNOWN_HOSTS,
    CONF_PROBE_ENABLED,
    CONF_PROBE_INTERVAL,
    CONF_PROBE_VIDEO_DEVICES,
    CONF_URL_OVERRIDES,
    DEFAULT_GROUP_PROBE_ENABLED,
    DEFAULT_PROBE_ENABLED,
    DEFAULT_PROBE_INTERVAL,
    DEFAULT_PROBE_VIDEO_DEVICES,
    DOMAIN,
    MIN_PROBE_INTERVAL,
)
from .urls import normalize_override

if TYPE_CHECKING:
    from . import CastConfigEntry

CONF_MORE_OPTIONS = "more_options"
CONF_HEALTH = "health"
CONF_EDIT_URL_OVERRIDES = "edit_url_overrides"
CONF_ADD_ANOTHER = "add_another"
HEALTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_PROBE_ENABLED, default=DEFAULT_PROBE_ENABLED): bool,
        vol.Optional(CONF_PROBE_INTERVAL, default=DEFAULT_PROBE_INTERVAL): vol.All(
            NumberSelector(
                NumberSelectorConfig(
                    min=MIN_PROBE_INTERVAL,
                    max=3600,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Coerce(int),
            vol.Range(min=MIN_PROBE_INTERVAL, max=3600),
        ),
        vol.Optional(
            CONF_GROUP_PROBE_ENABLED, default=DEFAULT_GROUP_PROBE_ENABLED
        ): bool,
        vol.Optional(
            CONF_PROBE_VIDEO_DEVICES, default=DEFAULT_PROBE_VIDEO_DEVICES
        ): bool,
        vol.Optional(CONF_EDIT_URL_OVERRIDES, default=False): bool,
    }
)
KNOWN_HOSTS_SCHEMA = vol.Schema(
    {
        vol.Optional(
            CONF_KNOWN_HOSTS,
        ): SelectSelector(
            SelectSelectorConfig(custom_value=True, options=[], multiple=True),
        )
    }
)
OPTIONS_SCHEMA = KNOWN_HOSTS_SCHEMA.extend(
    {
        vol.Required(CONF_MORE_OPTIONS): section(
            vol.Schema(
                {
                    vol.Optional(CONF_UUID): SelectSelector(
                        SelectSelectorConfig(
                            custom_value=True, options=[], multiple=True
                        ),
                    ),
                    vol.Optional(CONF_IGNORE_CEC): SelectSelector(
                        SelectSelectorConfig(
                            custom_value=True, options=[], multiple=True
                        ),
                    ),
                }
            ),
            SectionConfig(collapsed=True),
        ),
        vol.Optional(CONF_HEALTH, default={}): section(
            HEALTH_SCHEMA, SectionConfig(collapsed=True)
        ),
    }
)


class FlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: CastConfigEntry,
    ) -> CastOptionsFlowHandler:
        """Get the options flow for this handler."""
        return CastOptionsFlowHandler()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_config()

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a flow initialized by zeroconf discovery."""
        await self.async_set_unique_id(DOMAIN)

        return await self.async_step_confirm()

    async def async_step_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the setup."""
        if user_input is not None:
            known_hosts = _trim_items(user_input.get(CONF_KNOWN_HOSTS, []))
            return self.async_create_entry(
                title="Google Cast",
                data=self._get_data(known_hosts=known_hosts),
            )

        return self.async_show_form(step_id="config", data_schema=KNOWN_HOSTS_SCHEMA)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the setup."""
        if user_input is not None or not onboarding.async_is_onboarded(self.hass):
            return self.async_create_entry(title="Google Cast", data=self._get_data())

        return self.async_show_form(step_id="confirm")

    def _get_data(
        self, *, known_hosts: list[str] | None = None
    ) -> dict[str, list[str]]:
        return {
            CONF_IGNORE_CEC: [],
            CONF_KNOWN_HOSTS: known_hosts or [],
            CONF_UUID: [],
        }


class CastOptionsFlowHandler(OptionsFlow):
    """Handle Google Cast options."""

    _data: dict[str, Any]
    _options: dict[str, Any]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the Google Cast options."""
        if user_input is not None:
            ignore_cec = _trim_items(
                user_input[CONF_MORE_OPTIONS].get(CONF_IGNORE_CEC, [])
            )
            known_hosts = _trim_items(user_input.get(CONF_KNOWN_HOSTS, []))
            wanted_uuid = _trim_items(user_input[CONF_MORE_OPTIONS].get(CONF_UUID, []))
            self._data = dict(self.config_entry.data)
            self._data[CONF_IGNORE_CEC] = ignore_cec
            self._data[CONF_KNOWN_HOSTS] = known_hosts
            self._data[CONF_UUID] = wanted_uuid

            health = dict(user_input.get(CONF_HEALTH, {}))
            edit_overrides = bool(health.pop(CONF_EDIT_URL_OVERRIDES, False))
            self._options = {**self.config_entry.options, **health}
            if edit_overrides:
                return await self.async_step_url_overrides()
            return self._async_finish()

        suggested: dict[str, Any] = {
            CONF_MORE_OPTIONS: {},
            CONF_HEALTH: {
                key: self.config_entry.options[key]
                for key in (
                    CONF_PROBE_ENABLED,
                    CONF_PROBE_INTERVAL,
                    CONF_GROUP_PROBE_ENABLED,
                    CONF_PROBE_VIDEO_DEVICES,
                )
                if key in self.config_entry.options
            },
        }
        if CONF_KNOWN_HOSTS in self.config_entry.data:
            suggested[CONF_KNOWN_HOSTS] = self.config_entry.data[CONF_KNOWN_HOSTS]
        for key in (CONF_UUID, CONF_IGNORE_CEC):
            if key not in self.config_entry.data:
                continue
            suggested[CONF_MORE_OPTIONS][key] = self.config_entry.data[key]

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, suggested),
        )

    @callback
    def _async_finish(self) -> ConfigFlowResult:
        """Write data and options in one update so the listener runs once."""
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self._data, options=self._options
        )
        return self.async_create_entry(title="", data=self._options)

    async def async_step_url_overrides(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set or clear the base URL one device fetches media from."""
        overrides: dict[str, str] = dict(self._options.get(CONF_URL_OVERRIDES) or {})
        errors: dict[str, str] = {}
        if user_input is not None:
            device = str(user_input[CONF_DEVICE]).strip()
            raw = str(user_input.get(CONF_URL) or "").strip()
            if not raw:
                overrides.pop(device, None)
            elif (base := normalize_override(raw)) is None:
                errors[CONF_URL] = "invalid_url"
            else:
                overrides[device] = base
            if not errors:
                self._options[CONF_URL_OVERRIDES] = overrides
                if not user_input.get(CONF_ADD_ANOTHER):
                    return self._async_finish()

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE): SelectSelector(
                    SelectSelectorConfig(
                        options=self._device_options(overrides),
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                ),
                vol.Optional(CONF_URL): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Optional(CONF_ADD_ANOTHER, default=False): bool,
            }
        )
        current = (
            ", ".join(
                f"{self._device_label(uuid)}: {base}"
                for uuid, base in overrides.items()
            )
            or "none"
        )
        return self.async_show_form(
            step_id="url_overrides",
            data_schema=schema,
            errors=errors,
            description_placeholders={"overrides": current},
        )

    def _device_label(self, uuid: str) -> str:
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is not None and runtime.ledger is not None:
            for health in runtime.ledger.devices.values():
                if str(health.uuid) == uuid and health.name:
                    return f"{health.name} ({health.host or 'no address'})"
        return uuid

    def _device_options(self, overrides: dict[str, str]) -> list[SelectOptionDict]:
        """Every device the running entry knows, plus any with an override."""
        uuids: dict[str, str] = {}
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is not None and runtime.ledger is not None:
            for health in runtime.ledger.devices.values():
                uuids[str(health.uuid)] = self._device_label(str(health.uuid))
        for uuid in overrides:
            uuids.setdefault(uuid, uuid)
        return [
            SelectOptionDict(
                value=uuid,
                label=f"{label} [{overrides[uuid]}]" if uuid in overrides else label,
            )
            for uuid, label in sorted(uuids.items(), key=lambda item: item[1].lower())
        ]


def _trim_items(items: list[str]) -> list[str]:
    return [x.strip() for x in items if x.strip()]
