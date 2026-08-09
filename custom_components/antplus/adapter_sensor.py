"""Diagnostic entities for physical ANT USB adapters."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .adapter import AntAdapterManager, AdapterPresence


async def async_setup_adapter_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    manager: AntAdapterManager,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one connection entity per remembered/seen physical adapter."""
    known: set[str] = set()

    def add(stable_key: str) -> None:
        if stable_key in known:
            return
        if manager.get(stable_key) is None:
            return
        known.add(stable_key)
        async_add_entities(
            [AntUsbAdapterConnectionSensor(manager, stable_key)],
            update_before_add=False,
        )

    for stable_key in manager.records:
        add(stable_key)

    def changed(stable_key: str) -> None:
        hass.loop.call_soon_threadsafe(add, stable_key)

    entry.async_on_unload(manager.add_callback(changed))


class AntUsbAdapterConnectionSensor(SensorEntity):
    """Connection/availability of one physical ANT USB adapter."""

    _attr_name = "Connection"
    _attr_icon = "mdi:usb"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        manager: AntAdapterManager,
        stable_key: str,
    ) -> None:
        self.manager = manager
        self.stable_key = stable_key
        self._attr_unique_id = f"antplus_usb_adapter_{stable_key}_connection"

    @property
    def _record(self) -> AdapterPresence | None:
        return self.manager.get(self.stable_key)

    @property
    def available(self) -> bool:
        record = self._record
        return bool(record and record.available)

    @property
    def native_value(self):
        record = self._record
        if record is None or not record.available:
            return None
        return record.connection

    @property
    def extra_state_attributes(self):
        record = self._record
        if record is None:
            return {}
        return {
            "adapter_id": self.stable_key,
            "local": record.local_present,
            "remote_gateways": sorted(record.remote_gateways or {}),
            "sources": record.sources,
        }

    @property
    def device_info(self) -> DeviceInfo | None:
        record = self._record
        if record is None:
            return None

        adapter = record.adapter
        return DeviceInfo(
            identifiers={adapter.ha_identifier},
            name=adapter.name,
            manufacturer=adapter.manufacturer or "Dynastream / Garmin",
            model=adapter.product or f"ANT USB {adapter.vid}:{adapter.pid}",
            serial_number=adapter.serial,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        def changed(stable_key: str) -> None:
            if stable_key != self.stable_key:
                return
            self.hass.loop.call_soon_threadsafe(
                self.async_write_ha_state
            )

        self.async_on_remove(self.manager.add_callback(changed))
