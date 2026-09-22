"""Repair fix flows."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .const import DOMAIN
from .issues import ISSUE_STALE_DEVICE


class StaleDeviceFlow(RepairsFlow):
    """Confirm and remove a registry device that discovery no longer reports."""

    def __init__(self, hass: HomeAssistant, issue_id: str, device_id: str) -> None:
        """Initialize the flow."""
        self._issue_id = issue_id
        self._device_id = device_id
        device = dr.async_get(hass).async_get(device_id)
        self._placeholders = {
            "name": (device.name_by_user or device.name or device_id) if device else device_id
        }

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Remove the device on confirmation."""
        if user_input is not None:
            registry = dr.async_get(self.hass)
            if registry.async_get(self._device_id) is not None:
                registry.async_remove_device(self._device_id)
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm", description_placeholders=self._placeholders
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Create a fix flow for an issue."""
    if issue_id.startswith(f"{ISSUE_STALE_DEVICE}.") and data and "device_id" in data:
        return StaleDeviceFlow(hass, issue_id, str(data["device_id"]))
    raise ValueError(f"No fix flow for {issue_id}")
