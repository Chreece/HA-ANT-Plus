# Button platform for HA ANT+ maintenance actions.

from __future__ import annotations

import logging
import re

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .subentries import ensure_sensor_subentry
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
    receiver: AntPlusReceiver = hass.data[DOMAIN][entry.entry_id]
    sensors_subentry_id = ensure_sensor_subentry(hass, entry)
    async_add_entities(
        [AntPlusCleanupStaleDevicesButton(hass, entry, receiver)],
        update_before_add=False,
        subentry_id=sensors_subentry_id,
    )


class AntPlusCleanupStaleDevicesButton(ButtonEntity):
    _attr_name = "Clean stale ANT+ devices"
    _attr_unique_id = "antplus_sensors_cleanup_stale_devices"
    _attr_icon = "mdi:broom"
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        receiver: AntPlusReceiver,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._receiver = receiver
        self._last_removed: list[int] = []


    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self):
        return {
            "scope": "all_ant_sensors",
            "confirmed_ant_devices": sorted(self._receiver.devices),
            "last_removed_count": len(self._last_removed),
            "last_removed_ant_ids": self._last_removed,
        }

    async def async_press(self) -> None:
        self._last_removed = await async_cleanup_stale_raw_devices(
            self._hass,
            self._entry,
            self._receiver,
        )
        _LOGGER.info(
            "ANT+ stale-device cleanup completed: removed %d device(s): %s",
            len(self._last_removed),
            self._last_removed,
        )
        self.async_write_ha_state()
