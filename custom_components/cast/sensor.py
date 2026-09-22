"""Delivery health sensors for Cast devices."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import CONF_UUID, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import CastConfigEntry
from .const import DOMAIN, SIGNAL_CAST_DISCOVERED, SIGNAL_HEALTH_UPDATED
from .health import DeliveryLedger, DeliveryOutcome, DeviceHealth
from .helpers import ChromecastInfo

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: CastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create health sensors for every discovered cast device."""
    ledger = config_entry.runtime_data.get_ledger(hass, config_entry)
    wanted_uuids = config_entry.data.get(CONF_UUID) or None
    added = config_entry.runtime_data.added_health_devices

    @callback
    def async_cast_discovered(info: ChromecastInfo) -> None:
        if wanted_uuids is not None and str(info.uuid) not in wanted_uuids:
            return
        if info.is_dynamic_group or info.uuid in added:
            return
        added.add(info.uuid)
        ledger.async_update_identity(
            info.uuid,
            name=info.friendly_name,
            host=info.cast_info.host,
            port=info.cast_info.port,
            seen=True,
        )
        async_add_entities(
            [
                CastOutcomeSensor(ledger, info),
                CastLastSuccessSensor(ledger, info),
            ]
        )

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_CAST_DISCOVERED, async_cast_discovered)
    )


class CastHealthSensor(SensorEntity):
    """Base class for the per-device health sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, ledger: DeliveryLedger, info: ChromecastInfo, key: str) -> None:
        """Initialize the sensor."""
        self._ledger = ledger
        self._uuid: UUID = info.uuid
        self._attr_translation_key = key
        self._attr_unique_id = f"{info.uuid}_{key}"
        # Identical to the media player's device record so the device carries
        # the cast name whichever platform registers it first.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(info.uuid).replace("-", ""))},
            manufacturer=str(info.cast_info.manufacturer),
            model=info.cast_info.model_name,
            name=str(info.friendly_name),
        )

    @property
    def health(self) -> DeviceHealth:
        """Return the live health record for this device."""
        return self._ledger.device(self._uuid)

    async def async_added_to_hass(self) -> None:
        """Subscribe to ledger updates for this device."""
        await super().async_added_to_hass()

        @callback
        def _updated(uuid: UUID) -> None:
            if uuid == self._uuid:
                self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_HEALTH_UPDATED, _updated)
        )


class CastOutcomeSensor(CastHealthSensor):
    """The outcome of the last delivery attempt to a device."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, ledger: DeliveryLedger, info: ChromecastInfo) -> None:
        """Initialize the sensor."""
        super().__init__(ledger, info, "tts_outcome")
        self._attr_options = [outcome.value for outcome in DeliveryOutcome]

    @property
    def native_value(self) -> str:
        """Return the last outcome."""
        return self.health.last_outcome.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the evidence behind the outcome."""
        health = self.health
        record = health.last_record
        return {
            "source": record.source if record else None,
            "content_id": record.content_id if record else None,
            "url_source": record.url_source if record else None,
            "error": record.error if record else None,
            "responded": record.responded if record else None,
            "elapsed": record.elapsed if record else None,
            "player_state": record.player_state if record else None,
            "idle_reason": record.idle_reason if record else None,
            "checked_at": record.resolved_at.isoformat() if record else None,
            "consecutive_failures": health.consecutive_failures,
            "consecutive_timeouts": health.consecutive_timeouts,
            "circuit_open": health.circuit_open_until is not None,
            "subnet_mismatch": health.subnet_mismatch,
            "host": health.host,
            "port": health.port,
        }


class CastLastSuccessSensor(CastHealthSensor, RestoreSensor):
    """When a delivery to the device last succeeded."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, ledger: DeliveryLedger, info: ChromecastInfo) -> None:
        """Initialize the sensor."""
        super().__init__(ledger, info, "last_tts_success")

    async def async_added_to_hass(self) -> None:
        """Restore the last success across restarts."""
        await super().async_added_to_hass()
        if self.health.last_success is not None:
            return
        if (last := await self.async_get_last_sensor_data()) and isinstance(
            last.native_value, str
        ):
            self.health.last_success = dt_util.parse_datetime(last.native_value)
        elif last and isinstance(last.native_value, datetime):
            self.health.last_success = last.native_value

    @property
    def native_value(self) -> datetime | None:
        """Return the last success timestamp."""
        return self.health.last_success
