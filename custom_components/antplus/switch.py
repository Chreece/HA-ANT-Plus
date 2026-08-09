"""Switch platform for per-physical-adapter ANT+ capture."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .adapter import AntAdapterManager, AdapterPresence
from .const import DOMAIN
from .subentries import ensure_adapter_subentry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one Capture switch for every physical ANT USB adapter."""
    receiver = hass.data[DOMAIN][entry.entry_id]
    manager: AntAdapterManager = receiver.adapter_manager
    known: set[str] = set()

    def add(stable_key: str) -> None:
        if stable_key in known or manager.get(stable_key) is None:
            return
        known.add(stable_key)
        record = manager.get(stable_key)
        subentry_id = ensure_adapter_subentry(hass, entry, stable_key, record.adapter.subentry_name)
        async_add_entities(
            [AntUsbAdapterCaptureSwitch(manager, stable_key)],
            update_before_add=False,
            config_subentry_id=subentry_id,
        )

    for stable_key in manager.records:
        add(stable_key)

    def changed(stable_key: str) -> None:
        hass.loop.call_soon_threadsafe(add, stable_key)

    entry.async_on_unload(manager.add_callback(changed))


class AntUsbAdapterCaptureSwitch(SwitchEntity):
    """Capture control for one physical ANT USB adapter."""

    _attr_name = "Capture"
    _attr_icon = "mdi:access-point"

    def __init__(
        self,
        manager: AntAdapterManager,
        stable_key: str,
    ) -> None:
        self.manager = manager
        self.stable_key = stable_key
        self._attr_unique_id = f"antplus_usb_adapter_{stable_key}_capture"

    @property
    def _record(self) -> AdapterPresence | None:
        return self.manager.get(self.stable_key)

    @property
    def available(self) -> bool:
        record = self._record
        return bool(record and record.available)

    @property
    def is_on(self) -> bool:
        record = self._record
        return bool(record and record.displayed_capture)

    @property
    def extra_state_attributes(self):
        record = self._record
        if record is None:
            return {}
        return {
            "adapter_id": self.stable_key,
            "connection": record.connection,
            "local": record.local_present,
            "remote_gateways": sorted(record.remote_gateways or {}),
            "desired_capture": record.desired_capture,
            "confirmed_capture": record.capture_enabled,
            "pending_capture": record.pending_capture,
            "capture_error": record.capture_error,
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

    async def async_turn_on(self, **kwargs) -> None:
        await self.manager.async_set_capture(self.stable_key, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.manager.async_set_capture(self.stable_key, False)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        def changed(stable_key: str) -> None:
            if stable_key != self.stable_key:
                return
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

        self.async_on_remove(self.manager.add_callback(changed))
