"""Switch platform for ANT+ capture control."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([AntPlusCaptureSwitch(receiver)])


class AntPlusCaptureSwitch(SwitchEntity):
    """Start or stop ANT+ continuous capture."""

    _attr_name = "Capture"
    _attr_unique_id = "antplus_capture"
    _attr_icon = "mdi:access-point"

    def __init__(self, receiver: AntPlusReceiver) -> None:
        self.receiver = receiver

    @property
    def is_on(self) -> bool:
        return self.receiver.running

    @property
    def available(self) -> bool:
        # The control itself must stay usable while stopped or errored.
        return True

    @property
    def extra_state_attributes(self):
        return {
            "status": self.receiver.state,
            "last_error": self.receiver.error,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "usb_adapter")},
            name="ANT+ USB Adapter",
            manufacturer="Dynastream / Garmin",
            model="ANT+ USB Adapter",
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self.hass.async_add_executor_job(self.receiver.start)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.hass.async_add_executor_job(self.receiver.stop)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        def changed() -> None:
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

        self.async_on_remove(self.receiver.add_state_callback(changed))
