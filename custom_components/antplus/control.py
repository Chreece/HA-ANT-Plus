"""ANT+ active-control packet builders and transport routing."""
from __future__ import annotations

from datetime import datetime, timezone

from .const import (
    DEVICE_INACTIVITY_TIMEOUT,
    DEVICE_TYPE_DROPPER,
    DEVICE_TYPE_FITNESS_EQUIPMENT,
    DEVICE_TYPE_LEV,
    DEVICE_TYPE_TIRE_PRESSURE,
)


PROFILE_PERIOD = {
    DEVICE_TYPE_FITNESS_EQUIPMENT: 8192,
    DEVICE_TYPE_LEV: 8192,
    DEVICE_TYPE_DROPPER: 8192,
    DEVICE_TYPE_TIRE_PRESSURE: 8192,
}


def fe_target_power_payload(power_w: float) -> bytes:
    if not 0 <= power_w <= 4000:
        raise ValueError("Target power must be between 0 and 4000 W")
    raw = int(round(power_w * 4))
    return bytes((0x31, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, raw & 0xFF, (raw >> 8) & 0xFF))


def fe_basic_resistance_payload(resistance_percent: float) -> bytes:
    if not 0 <= resistance_percent <= 100:
        raise ValueError("Basic resistance must be between 0 and 100 %")
    raw = int(round(resistance_percent * 2))
    return bytes((0x30, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, raw & 0xFF))


def lev_payload(
    *,
    assist_level: int | None = None,
    regenerative_level: int | None = None,
    rear_gear: int = 0,
    front_gear: int = 0,
    lights: bool = False,
    high_beam: bool = False,
    turn_left: bool = False,
    turn_right: bool = False,
    wheel_circumference: int | None = None,
    manufacturer_id: int = 0xFFFF,
) -> bytes:
    for value, name in ((assist_level, "assist"), (regenerative_level, "regenerative")):
        if value is not None and not 0 <= int(value) <= 7:
            raise ValueError(f"LEV {name} level must be 0..7")
    if not 0 <= rear_gear <= 7 or not 0 <= front_gear <= 3:
        raise ValueError("LEV rear gear must be 0..7 and front gear 0..3")
    wheel = 0xFFF if wheel_circumference is None else int(wheel_circumference)
    if not 0 <= wheel <= 0xFFF:
        raise ValueError("LEV wheel circumference must fit 12 bits")
    page = [0] * 8
    page[0] = 0x10
    page[1] = wheel & 0xFF
    page[2] = (wheel >> 8) & 0x0F
    if assist_level is None and regenerative_level is None:
        page[3] = 0xFF
    else:
        page[3] = ((int(assist_level or 0) & 0x07) << 3) | (int(regenerative_level or 0) & 0x07)
    display = (
        ((rear_gear & 0x07) << 6)
        | ((front_gear & 0x03) << 4)
        | (int(lights) << 3)
        | (int(high_beam) << 2)
        | (int(turn_left) << 1)
        | int(turn_right)
    )
    page[4] = display & 0xFF
    page[5] = (display >> 8) & 0xFF
    page[6] = manufacturer_id & 0xFF
    page[7] = (manufacturer_id >> 8) & 0xFF
    return bytes(page)


def dropper_payload(
    *,
    unlocked: bool,
    command_sequence: int,
    unlock_delay_s: float | None = None,
    store_unlock_delay: bool = False,
) -> bytes:
    page = [0] * 8
    page[0] = 0x20
    page[1] = 0xFF
    page[2] = 0xFF
    page[3] = command_sequence & 0xFF
    page[4] = 1 if unlocked else 0
    if unlock_delay_s is None:
        raw_delay = 0x7F
    else:
        if not 0 <= unlock_delay_s <= 1.26:
            raise ValueError("Dropper unlock delay must be 0..1.26 seconds")
        raw_delay = int(round(unlock_delay_s * 100)) & 0x7F
    page[7] = raw_delay | (0x80 if store_unlock_delay else 0)
    return bytes(page)



def tpms_parameter_payload(
    *,
    position: int = 0,
    barometric_pressure_mbar: int = 0x8000,
    low_pressure_alarm_mbar: int = 0x8000,
    high_pressure_alarm_mbar: int = 0x8000,
    set_position: bool = False,
    set_barometric: bool = False,
    set_low_pressure: bool = False,
    set_high_pressure: bool = False,
) -> bytes:
    """Build OpenANT's ANT+ TPMS get/set parameter page (0x10)."""
    if not 0 <= int(position) <= 0x0F:
        raise ValueError("TPMS position must fit 4 bits")
    for value, name in (
        (barometric_pressure_mbar, "barometric pressure"),
        (low_pressure_alarm_mbar, "low pressure alarm"),
        (high_pressure_alarm_mbar, "high pressure alarm"),
    ):
        if not 0 <= int(value) <= 0xFFFF:
            raise ValueError(f"TPMS {name} must fit 16 bits")
    flags = (
        int(bool(set_position))
        | (int(bool(set_barometric)) << 1)
        | (int(bool(set_high_pressure)) << 2)
        | (int(bool(set_low_pressure)) << 3)
    )
    return bytes((
        0x10,
        (int(position) & 0x0F) | ((flags & 0x0F) << 4),
        int(barometric_pressure_mbar) & 0xFF,
        (int(barometric_pressure_mbar) >> 8) & 0xFF,
        int(low_pressure_alarm_mbar) & 0xFF,
        (int(low_pressure_alarm_mbar) >> 8) & 0xFF,
        int(high_pressure_alarm_mbar) & 0xFF,
        (int(high_pressure_alarm_mbar) >> 8) & 0xFF,
    ))


def request_data_page_payload(requested_page: int, count: int = 1) -> bytes:
    """Build ANT+ Common Page 70 request-data-page command."""
    if not 0 <= int(requested_page) <= 0xFF:
        raise ValueError("Requested ANT+ page must be 0..255")
    if not 1 <= int(count) <= 0x7F:
        raise ValueError("Request count must be 1..127")
    return bytes((0x46, 0xFF, 0xFF, 0xFF, 0xFF, int(count) & 0x7F, int(requested_page) & 0xFF, 0x01))

def parse_raw_payload(value) -> bytes:
    """Normalize an HA raw control payload to exactly eight bytes."""
    if isinstance(value, str):
        cleaned = value.replace(" ", "").replace(":", "").replace("-", "")
        payload = bytes.fromhex(cleaned)
    else:
        payload = bytes(int(item) for item in value)
    if len(payload) != 8:
        raise ValueError("ANT+ payload must contain exactly 8 bytes")
    return payload

def device_control_available(receiver, device_id: int, device_type: int) -> bool:
    device = receiver.devices.get(device_id)
    if device is None or device_type not in device.profiles or device.last_seen is None:
        return False
    age = (datetime.now(timezone.utc) - device.last_seen).total_seconds()
    if age > DEVICE_INACTIVITY_TIMEOUT:
        return False
    manager = getattr(receiver, "adapter_manager", None)
    return bool(manager and manager.can_control_device(device_id))


async def async_send(receiver, device_id: int, device_type: int, payload: bytes) -> None:
    manager = receiver.adapter_manager
    await manager.async_send_control(
        device_id=device_id,
        device_type=device_type,
        payload=payload,
        period=PROFILE_PERIOD[device_type],
    )
