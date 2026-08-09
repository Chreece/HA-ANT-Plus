"""Config-subentry ownership helpers for HA ANT+."""
from __future__ import annotations
from types import MappingProxyType
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from .const import DOMAIN

SENSORS_SUBENTRY_UNIQUE_ID = "antplus_sensors"

def adapter_subentry_unique_id(stable_key: str) -> str:
    return f"antplus_adapter:{stable_key}"

def find_subentry_id(entry: ConfigEntry, unique_id: str) -> str | None:
    return next((sid for sid, sub in entry.subentries.items() if sub.unique_id == unique_id), None)

def ensure_subentry(hass, entry, *, subentry_type, title, unique_id, data=None):
    existing = find_subentry_id(entry, unique_id)
    if existing:
        return existing
    sub = ConfigSubentry(data=MappingProxyType(data or {}), subentry_type=subentry_type, title=title, unique_id=unique_id)
    hass.config_entries.async_add_subentry(entry, sub)
    return sub.subentry_id

def ensure_sensor_subentry(hass, entry):
    return ensure_subentry(hass, entry, subentry_type="sensors", title="ANT+ Sensors", unique_id=SENSORS_SUBENTRY_UNIQUE_ID)

def ensure_adapter_subentry(hass, entry, stable_key, title):
    return ensure_subentry(hass, entry, subentry_type="adapter", title=title, unique_id=adapter_subentry_unique_id(stable_key), data={"stable_key": stable_key})

def migrate_devices_to_subentries(hass, entry, manager):
    registry = dr.async_get(hass)
    sensors_sid = ensure_sensor_subentry(hass, entry)
    adapter_sids = {k: ensure_adapter_subentry(hass, entry, k, r.adapter.name) for k, r in manager.records.items()}
    for device in list(registry.devices.values()):
        if device.config_entry_id != entry.entry_id:
            continue
        if any(domain == DOMAIN and str(value).isdigit() for domain, value in device.identifiers):
            if device.config_subentry_id != sensors_sid:
                registry.async_update_device(device.id, new_config_subentry_id=sensors_sid)
            continue
        for key, record in manager.records.items():
            if record.adapter.ha_identifier in device.identifiers:
                sid = adapter_sids[key]
                if device.config_subentry_id != sid:
                    registry.async_update_device(device.id, new_config_subentry_id=sid)
                break
