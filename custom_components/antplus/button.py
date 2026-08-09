# Button platform for HA ANT+ maintenance actions.

from __future__ import annotations

import logging
import re

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .receiver import AntPlusReceiver

_LOGGER = logging.getLogger(__name__)

_RAW_LAST_PAGE_RE = re.compile(r"^\d+_profile_\d+_last_page$")
_RAW_PAGE_RE = re.compile(r"^\d+_profile_\d+_page_\d+_raw$")


def _is_raw_fallback_unique_id(unique_id: str) -> bool:
    return bool(
        _RAW_LAST_PAGE_RE.fullmatch(unique_id)
        or _RAW_PAGE_RE.fullmatch(unique_id)
    )


def _numeric_ant_identifier(device: dr.DeviceEntry) -> int | None:
    for domain, value in device.identifiers:
        if domain != DOMAIN:
            continue
        value_str = str(value)
        if value_str.isdigit():
            return int(value_str)
    return None


async def async_cleanup_stale_raw_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    receiver: AntPlusReceiver,
) -> list[int]:
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    confirmed_ids = set(receiver.devices)
    removed: list[int] = []

    for device in list(device_registry.devices.values()):
        if entry.entry_id not in device.config_entries:
            continue

        ant_id = _numeric_ant_identifier(device)
        if ant_id is None or ant_id in confirmed_ids:
            continue

        entities = [
            entity
            for entity in entity_registry.entities.values()
            if entity.device_id == device.id and entity.platform == DOMAIN
        ]

        if not entities:
            continue

        if not all(
            _is_raw_fallback_unique_id(entity.unique_id or "")
            for entity in entities
        ):
            continue

        for entity in list(entities):
            entity_registry.async_remove(entity.entity_id)

        device_registry.async_remove_device(device.id)
        removed.append(ant_id)

        _LOGGER.info(
            "Removed stale raw-only ANT+ device %s (%d fallback entities)",
            ant_id,
            len(entities),
        )

    return sorted(removed)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one cleanup button for every physical ANT USB adapter."""
    receiver: AntPlusReceiver = hass.data[DOMAIN][entry.entry_id]
    manager = receiver.adapter_manager
    known: set[str] = set()

    def add(stable_key: str) -> None:
        if stable_key in known or manager.get(stable_key) is None:
            return
        known.add(stable_key)
        async_add_entities(
            [AntUsbAdapterCleanupStaleDevicesButton(hass, entry, receiver, manager, stable_key)],
            update_before_add=False,
        )

    for stable_key in manager.records:
        add(stable_key)

    def changed(stable_key: str) -> None:
        hass.loop.call_soon_threadsafe(add, stable_key)

    entry.async_on_unload(manager.add_callback(changed))


class AntUsbAdapterCleanupStaleDevicesButton(ButtonEntity):
    """Integration-wide sensor cleanup surfaced on one physical adapter."""

    _attr_name = "Clean stale ANT+ devices"
    _attr_icon = "mdi:broom"
    _attr_should_poll = False

    def __init__(self, hass, entry, receiver, manager, stable_key: str) -> None:
        self._hass = hass
        self._entry = entry
        self._receiver = receiver
        self._manager = manager
        self._stable_key = stable_key
        self._last_removed: list[int] = []
        self._attr_unique_id = f"antplus_usb_adapter_{stable_key}_cleanup_stale_devices"

    @property
    def _record(self):
        return self._manager.get(self._stable_key)

    @property
    def available(self) -> bool:
        record = self._record
        return bool(record and record.available)

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

    @property
    def extra_state_attributes(self):
        return {
            "scope": "all_ant_sensors",
            "adapter_id": self._stable_key,
            "confirmed_ant_devices": sorted(self._receiver.devices),
            "last_removed_count": len(self._last_removed),
            "last_removed_ant_ids": self._last_removed,
        }

    async def async_press(self) -> None:
        self._last_removed = await async_cleanup_stale_raw_devices(
            self._hass, self._entry, self._receiver
        )
        _LOGGER.info(
            "ANT+ cleanup requested from adapter %s: removed %d device(s): %s",
            self._stable_key,
            len(self._last_removed),
            self._last_removed,
        )
        self.async_write_ha_state()
