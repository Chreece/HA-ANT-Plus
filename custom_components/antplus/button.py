"""Button platform for ANT+ capture control."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .receiver import AntPlusReceiver


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    receiver: AntPlusReceiver = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AntPlusCaptureButton(receiver)])


class AntPlusCaptureButton(ButtonEntity):
    """Toggle ANT+ capture on/off."""

    _attr_name = "Start / Stop Capture"
    _attr_unique_id = "antplus_capture_toggle"
    _attr_entity_registry_enabled_default = False

    def __init__(self, receiver: AntPlusReceiver) -> None:
        self.receiver = receiver

    @property
    def icon(self) -> str:
        return "mdi:stop-circle-outline" if self.receiver.running else "mdi:play-circle-outline"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "usb_adapter")},
            name="ANT+ USB Adapter",
            manufacturer="Dynastream / Garmin",
            model="ANT+ USB Adapter",
        )

    async def async_press(self) -> None:
        await self.hass.async_add_executor_job(self.receiver.toggle)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        def changed() -> None:
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

        self.async_on_remove(self.receiver.add_state_callback(changed))
