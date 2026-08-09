"""Switch platform for global HA ANT+ capture."""

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
    """Set up the global HA ANT+ capture switch."""
    receiver: AntPlusReceiver = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [AntPlusCaptureSwitch(receiver)],
        update_before_add=False,
    )


class AntPlusCaptureSwitch(SwitchEntity):
    """Enable or disable ANT+ capture from every source."""

    _attr_name = "Capture"
    _attr_unique_id = "antplus_capture"
    _attr_icon = "mdi:access-point"

    def __init__(self, receiver: AntPlusReceiver) -> None:
        self.receiver = receiver

    @property
    def is_on(self) -> bool:
        """Return the global capture state."""
        return self.receiver.capture_enabled

    @property
    def available(self) -> bool:
        """The global control is always available."""
        return True

    @property
    def extra_state_attributes(self):
        """Expose transport diagnostics."""
        sources = set()

        for device in self.receiver.snapshot().values():
            sources.update(
                device.decoder_state.get("sources", set())
            )

        return {
            "local_receiver_status": self.receiver.state,
            "local_receiver_error": self.receiver.error,
            "sources_seen": sorted(sources),
            "remote_capture_enabled": self.receiver.capture_enabled,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Represent the global HA ANT+ hub."""
        return DeviceInfo(
            identifiers={(DOMAIN, "hub")},
            name="HA ANT+",
            manufacturer="HA ANT+",
            model="ANT+ Hub",
        )

    async def async_turn_on(self, **kwargs) -> None:
        """Enable capture from local and remote ANT+ adapters."""
        await self.hass.async_add_executor_job(
            self.receiver.enable_capture
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable capture from local and remote ANT+ adapters."""
        await self.hass.async_add_executor_job(
            self.receiver.disable_capture
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register receiver state updates."""
        await super().async_added_to_hass()

        def changed() -> None:
            self.hass.loop.call_soon_threadsafe(
                self.async_write_ha_state
            )

        self.async_on_remove(
            self.receiver.add_state_callback(changed)
        )
