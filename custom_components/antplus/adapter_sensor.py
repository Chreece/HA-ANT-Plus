"""Diagnostic entities for physical ANT USB adapters."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .adapter import AntAdapterManager, AdapterPresence
from .openant_bridge import supported_profile_types
from .profile_support import native_profile_types, profile_support_rows
from .subentries import ensure_adapter_subentry


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
        record = manager.get(stable_key)
        subentry_id = ensure_adapter_subentry(hass, entry, stable_key, record.adapter.subentry_name)
        async_add_entities(
            [
                AntUsbAdapterConnectionSensor(manager, stable_key),
                AntUsbAdapterSensorsSeenSensor(manager, stable_key),
                AntUsbAdapterLastErrorSensor(manager, stable_key),
                AntUsbAdapterDecoderCoverageSensor(manager, stable_key),
            ],
            update_before_add=False,
            config_subentry_id=subentry_id,
        )

    for stable_key in manager.records:
        add(stable_key)

    def changed(stable_key: str) -> None:
        hass.loop.call_soon_threadsafe(add, stable_key)

    entry.async_on_unload(manager.add_callback(changed))


def _source_matches_adapter(source: str, stable_key: str) -> bool:
    """Match local:<adapter> or remote:<gateway>:<adapter>."""
    return source == f"local:{stable_key}" or source.endswith(f":{stable_key}")


def _sensor_ids_seen_by_adapter(manager: AntAdapterManager, stable_key: str) -> list[int]:
    """Return universal ANT sensor IDs observed through this adapter."""
    seen: list[int] = []
    for device_id, device in manager.receiver.snapshot().items():
        sources = device.decoder_state.get("sources", set())
        if any(_source_matches_adapter(str(source), stable_key) for source in sources):
            seen.append(device_id)
    return sorted(seen)


class AntUsbAdapterDiagnosticSensor(SensorEntity):
    """Base diagnostic entity for one physical ANT USB adapter."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager: AntAdapterManager, stable_key: str) -> None:
        self.manager = manager
        self.stable_key = stable_key

    @property
    def _record(self) -> AdapterPresence | None:
        return self.manager.get(self.stable_key)

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

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        def changed(stable_key: str) -> None:
            if stable_key != self.stable_key:
                return
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

        def receiver_changed() -> None:
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

        self.async_on_remove(self.manager.add_callback(changed))
        self.async_on_remove(self.manager.receiver.add_state_callback(receiver_changed))


class AntUsbAdapterConnectionSensor(AntUsbAdapterDiagnosticSensor):
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

class AntUsbAdapterSensorsSeenSensor(AntUsbAdapterDiagnosticSensor):
    """Count universal ANT sensors observed through this adapter."""

    _attr_name = "Sensors Seen"
    _attr_icon = "mdi:access-point-network"

    def __init__(self, manager: AntAdapterManager, stable_key: str) -> None:
        super().__init__(manager, stable_key)
        self._attr_unique_id = f"antplus_usb_adapter_{stable_key}_sensors_seen"

    @property
    def native_value(self):
        return len(_sensor_ids_seen_by_adapter(self.manager, self.stable_key))

    @property
    def extra_state_attributes(self):
        return {"ant_device_ids": _sensor_ids_seen_by_adapter(self.manager, self.stable_key)}


class AntUsbAdapterLastErrorSensor(AntUsbAdapterDiagnosticSensor):
    """Last capture error from this physical adapter."""

    _attr_name = "Last Capture Error"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, manager: AntAdapterManager, stable_key: str) -> None:
        super().__init__(manager, stable_key)
        self._attr_unique_id = f"antplus_usb_adapter_{stable_key}_last_error"

    @property
    def native_value(self):
        record = self._record
        return record.capture_error if record and record.capture_error else "none"


class AntUsbAdapterDecoderCoverageSensor(AntUsbAdapterDiagnosticSensor):
    """Decoder capability available to this adapter's packets."""

    _attr_name = "Decoder Coverage"
    _attr_icon = "mdi:code-json"
    _attr_entity_registry_enabled_default = False

    def __init__(self, manager: AntAdapterManager, stable_key: str) -> None:
        super().__init__(manager, stable_key)
        self._attr_unique_id = f"antplus_usb_adapter_{stable_key}_decoder_coverage"

    @property
    def native_value(self):
        return len(native_profile_types())

    @property
    def extra_state_attributes(self):
        from .decoder_adapters import decoder_backend_rows
        from .documented_profiles import (
            DOCUMENTED_FAMILIES_WITHOUT_CONFIRMED_DEVICE_TYPE,
            documented_profile_types,
        )
        return {
            "decoder_backends": decoder_backend_rows(),
            "documented_profiles": sorted(documented_profile_types()),
            "native_profiles": sorted(native_profile_types()),
            "openant_profiles": sorted(supported_profile_types()),
            "openant_fallback_profiles": sorted(
                supported_profile_types() - native_profile_types()
            ),
            "profile_matrix": profile_support_rows(),
            "documented_families_without_confirmed_device_type": list(
                DOCUMENTED_FAMILIES_WITHOUT_CONFIRMED_DEVICE_TYPE
            ),
            "raw_fallback_for_all_profiles": True,
        }
