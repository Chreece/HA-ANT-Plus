"""Select controls for ANT+ profiles with enumerated writable parameters."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_TIRE_PRESSURE, DOMAIN
from .control import async_send, device_control_available, tpms_parameter_payload
from .entity import AntPlusEntity
from .models import AntDevice
from .subentries import ensure_sensor_subentry

TPMS_POSITIONS = {"Unknown": 0, "Front": 1, "Rear": 2}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    receiver = hass.data[DOMAIN][entry.entry_id]
    subentry_id = ensure_sensor_subentry(hass, entry)
    known: set[int] = set()

    def add_for_device(device: AntDevice) -> None:
        if DEVICE_TYPE_TIRE_PRESSURE not in device.profiles or device.device_id in known:
            return
        known.add(device.device_id)
        async_add_entities([AntTpmsPosition(receiver, device)], update_before_add=False, config_subentry_id=subentry_id)

    for device in receiver.snapshot().values(): add_for_device(device)
    def changed(device: AntDevice) -> None: hass.loop.call_soon_threadsafe(add_for_device, device)
    entry.async_on_unload(receiver.add_device_callback(changed))

class AntTpmsPosition(AntPlusEntity, SelectEntity):
    _attr_options = list(TPMS_POSITIONS)
    _attr_icon = "mdi:car-tire-alert"
    def __init__(self, receiver, device):
        AntPlusEntity.__init__(self, receiver, device, "__control__")
        self._attr_unique_id = f"{device.device_id}_tpms_position"
        self._attr_name = "Sensor Position"
    @property
    def available(self): return device_control_available(self.receiver, self.ant_device_id, DEVICE_TYPE_TIRE_PRESSURE)
    @property
    def current_option(self):
        value = int(self.ant_device.decoder_state.get("tpms_control", {}).get("position", 0))
        return next((name for name, code in TPMS_POSITIONS.items() if code == value), "Unknown")
    async def async_select_option(self, option: str) -> None:
        position = TPMS_POSITIONS[option]
        state = self.ant_device.decoder_state.setdefault("tpms_control", {})
        state["position"] = position
        payload = tpms_parameter_payload(
            position=position,
            barometric_pressure_mbar=state.get("barometric_pressure_mbar", 0x8000),
            low_pressure_alarm_mbar=state.get("low_pressure_alarm_mbar", 0x8000),
            high_pressure_alarm_mbar=state.get("high_pressure_alarm_mbar", 0x8000),
            set_position=True,
        )
        await async_send(self.receiver, self.ant_device_id, DEVICE_TYPE_TIRE_PRESSURE, payload)
        self.async_write_ha_state()
