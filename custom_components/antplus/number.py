"""Active ANT+ numeric controls."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_FITNESS_EQUIPMENT, DEVICE_TYPE_LEV, DEVICE_TYPE_DROPPER, DEVICE_TYPE_TIRE_PRESSURE, DOMAIN
from .control import (
    async_send,
    device_control_available,
    dropper_payload,
    fe_basic_resistance_payload,
    fe_target_power_payload,
    lev_payload,
    tpms_parameter_payload,
)
from .entity import AntPlusEntity
from .models import AntDevice
from .subentries import ensure_sensor_subentry


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    receiver = hass.data[DOMAIN][entry.entry_id]
    subentry_id = ensure_sensor_subentry(hass, entry)
    known: set[tuple[int, str]] = set()

    def add_for_device(device: AntDevice) -> None:
        entities = []
        specs = []
        if DEVICE_TYPE_FITNESS_EQUIPMENT in device.profiles:
            specs.extend((
                ("fe_target_power", AntFeTargetPower),
                ("fe_basic_resistance", AntFeBasicResistance),
            ))
        if DEVICE_TYPE_LEV in device.profiles:
            specs.extend((
                ("lev_assist_level", AntLevAssistLevel),
                ("lev_regenerative_level", AntLevRegenerativeLevel),
                ("lev_rear_gear", AntLevRearGear),
                ("lev_front_gear", AntLevFrontGear),
                ("lev_wheel_circumference", AntLevWheelCircumference),
                ("lev_command_manufacturer_id", AntLevCommandManufacturerId),
            ))
        if DEVICE_TYPE_DROPPER in device.profiles:
            specs.append(("dropper_unlock_delay", AntDropperUnlockDelay))
        if DEVICE_TYPE_TIRE_PRESSURE in device.profiles:
            specs.extend((
                ("tpms_barometric_pressure", AntTpmsBarometricPressure),
                ("tpms_low_pressure_alarm", AntTpmsLowPressureAlarm),
                ("tpms_high_pressure_alarm", AntTpmsHighPressureAlarm),
            ))
        for key, cls in specs:
            ident=(device.device_id,key)
            if ident not in known:
                known.add(ident); entities.append(cls(receiver, device))
        if entities:
            async_add_entities(entities, update_before_add=False, config_subentry_id=subentry_id)

    for device in receiver.snapshot().values():
        add_for_device(device)
    def changed(device: AntDevice) -> None:
        hass.loop.call_soon_threadsafe(add_for_device, device)
    entry.async_on_unload(receiver.add_device_callback(changed))


class _AntControlNumber(AntPlusEntity, NumberEntity):
    control_profile: int
    def __init__(self, receiver, device, key, name, minimum, maximum, step, unit=None):
        AntPlusEntity.__init__(self, receiver, device, "__control__")
        self._attr_unique_id=f"{device.device_id}_{key}"
        self._attr_name=name
        self._attr_native_min_value=minimum
        self._attr_native_max_value=maximum
        self._attr_native_step=step
        self._attr_native_unit_of_measurement=unit
        self._attr_mode=NumberMode.BOX
        self._value=minimum
    @property
    def native_value(self): return self._value
    @property
    def available(self): return device_control_available(self.receiver, self.ant_device_id, self.control_profile)

class AntFeTargetPower(_AntControlNumber):
    control_profile=DEVICE_TYPE_FITNESS_EQUIPMENT
    def __init__(self,r,d): super().__init__(r,d,"fe_target_power","Target Power",0,4000,1,"W")
    async def async_set_native_value(self,value):
        await async_send(self.receiver,self.ant_device_id,self.control_profile,fe_target_power_payload(value)); self._value=value; self.async_write_ha_state()

class AntFeBasicResistance(_AntControlNumber):
    control_profile=DEVICE_TYPE_FITNESS_EQUIPMENT
    def __init__(self,r,d): super().__init__(r,d,"fe_basic_resistance","Basic Resistance",0,100,0.5,"%")
    async def async_set_native_value(self,value):
        await async_send(self.receiver,self.ant_device_id,self.control_profile,fe_basic_resistance_payload(value)); self._value=value; self.async_write_ha_state()

class _LevNumber(_AntControlNumber):
    control_profile=DEVICE_TYPE_LEV
    field=""
    def _current(self):
        state=self.ant_device.decoder_state.setdefault("lev_control",{})
        return state
    async def async_set_native_value(self,value):
        state=self._current(); state[self.field]=int(value)
        payload=lev_payload(assist_level=state.get("assist_level"),regenerative_level=state.get("regenerative_level"),rear_gear=state.get("rear_gear",0),front_gear=state.get("front_gear",0),lights=state.get("lights",False),high_beam=state.get("high_beam",False),turn_left=state.get("turn_left",False),turn_right=state.get("turn_right",False),wheel_circumference=state.get("wheel_circumference"),manufacturer_id=state.get("manufacturer_id",0xFFFF))
        await async_send(self.receiver,self.ant_device_id,self.control_profile,payload); self._value=value; self.async_write_ha_state()

class AntLevAssistLevel(_LevNumber):
    field="assist_level"
    def __init__(self,r,d): super().__init__(r,d,"lev_assist_level","Assist Level",0,7,1)
class AntLevRegenerativeLevel(_LevNumber):
    field="regenerative_level"
    def __init__(self,r,d): super().__init__(r,d,"lev_regenerative_level","Regenerative Level",0,7,1)
class AntLevRearGear(_LevNumber):
    field="rear_gear"
    def __init__(self,r,d): super().__init__(r,d,"lev_rear_gear","Rear Gear Command",0,7,1)
class AntLevFrontGear(_LevNumber):
    field="front_gear"
    def __init__(self,r,d): super().__init__(r,d,"lev_front_gear","Front Gear Command",0,3,1)

class AntLevWheelCircumference(_LevNumber):
    field="wheel_circumference"
    def __init__(self,r,d): super().__init__(r,d,"lev_wheel_circumference","Wheel Circumference",0,4095,1,"mm")
class AntLevCommandManufacturerId(_LevNumber):
    field="manufacturer_id"
    def __init__(self,r,d): super().__init__(r,d,"lev_command_manufacturer_id","Command Manufacturer ID",0,65535,1)

class AntDropperUnlockDelay(_AntControlNumber):
    control_profile=DEVICE_TYPE_DROPPER
    def __init__(self,r,d): super().__init__(r,d,"dropper_unlock_delay","Unlock Delay",0,1.26,0.01,"s")
    async def async_set_native_value(self,value):
        state=self.ant_device.decoder_state.setdefault("dropper_control",{}); state["unlock_delay_s"]=float(value); state["sequence"]=(int(state.get("sequence",0))+1)&0xFF
        payload=dropper_payload(unlocked=bool(state.get("unlocked",False)),command_sequence=state["sequence"],unlock_delay_s=float(value),store_unlock_delay=True)
        await async_send(self.receiver,self.ant_device_id,self.control_profile,payload); self._value=value; self.async_write_ha_state()


class _TpmsNumber(_AntControlNumber):
    control_profile=DEVICE_TYPE_TIRE_PRESSURE
    field=""
    flag=""
    def __init__(self,r,d,key,name): super().__init__(r,d,key,name,0,65535,1,"mbar")
    async def async_set_native_value(self,value):
        state=self.ant_device.decoder_state.setdefault("tpms_control",{})
        state[self.field]=int(value)
        payload=tpms_parameter_payload(
            position=state.get("position",0),
            barometric_pressure_mbar=state.get("barometric_pressure_mbar",0x8000),
            low_pressure_alarm_mbar=state.get("low_pressure_alarm_mbar",0x8000),
            high_pressure_alarm_mbar=state.get("high_pressure_alarm_mbar",0x8000),
            **{self.flag: True},
        )
        await async_send(self.receiver,self.ant_device_id,self.control_profile,payload)
        self._value=value
        self.async_write_ha_state()

class AntTpmsBarometricPressure(_TpmsNumber):
    field="barometric_pressure_mbar"; flag="set_barometric"
    def __init__(self,r,d): super().__init__(r,d,"tpms_barometric_pressure","Barometric Pressure Setting")
class AntTpmsLowPressureAlarm(_TpmsNumber):
    field="low_pressure_alarm_mbar"; flag="set_low_pressure"
    def __init__(self,r,d): super().__init__(r,d,"tpms_low_pressure_alarm","Low Pressure Alarm")
class AntTpmsHighPressureAlarm(_TpmsNumber):
    field="high_pressure_alarm_mbar"; flag="set_high_pressure"
    def __init__(self,r,d): super().__init__(r,d,"tpms_high_pressure_alarm","High Pressure Alarm")
