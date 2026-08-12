"""ANT+ active-control packet builders and transport routing."""
from __future__ import annotations

from datetime import datetime, timezone

from .const import (
    DEVICE_INACTIVITY_TIMEOUT,
    DEVICE_TYPE_CONTROLS,
    DEVICE_TYPE_DROPPER,
    DEVICE_TYPE_FITNESS_EQUIPMENT,
    DEVICE_TYPE_LEV,
    DEVICE_TYPE_POWER,
    DEVICE_TYPE_TIRE_PRESSURE,
)


GENERIC_CONTROL_COMMANDS = {
    "menu_up": 0,
    "menu_down": 1,
    "select": 2,
    "back": 3,
    "home": 4,
    "timer_start": 32,
    "timer_stop": 33,
    "timer_reset": 34,
    "length": 35,
    "lap": 36,
}


PROFILE_PERIOD = {
    DEVICE_TYPE_CONTROLS: 8192,
    DEVICE_TYPE_POWER: 8182,
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



def controls_generic_payload(
    command: str | int,
    *,
    sequence: int = 0,
    controller_serial: int = 0xFFFF,
    controller_manufacturer_id: int = 0xFFFF,
) -> bytes:
    """Build ANT+ Controls Generic Command common page 73 (0x49)."""
    if isinstance(command, str):
        try:
            command_raw = GENERIC_CONTROL_COMMANDS[command]
        except KeyError as err:
            raise ValueError(f"Unknown ANT+ generic control command: {command}") from err
    else:
        command_raw = int(command)
    if not 0 <= command_raw <= 0xFFFF:
        raise ValueError("ANT+ generic command must fit 16 bits")
    if not 0 <= int(sequence) <= 0xFF:
        raise ValueError("ANT+ generic control sequence must be 0..255")
    if not 0 <= int(controller_serial) <= 0xFFFF:
        raise ValueError("Controller serial must fit 16 bits")
    if not 0 <= int(controller_manufacturer_id) <= 0xFFFF:
        raise ValueError("Controller manufacturer ID must fit 16 bits")
    return bytes((
        0x49,
        int(controller_serial) & 0xFF,
        (int(controller_serial) >> 8) & 0xFF,
        int(controller_manufacturer_id) & 0xFF,
        (int(controller_manufacturer_id) >> 8) & 0xFF,
        int(sequence) & 0xFF,
        command_raw & 0xFF,
        (command_raw >> 8) & 0xFF,
    ))


def fe_wind_resistance_payload(
    *,
    wind_resistance_coefficient: float | None = None,
    wind_speed_kmh: float | None = None,
    drafting_factor: float | None = None,
) -> bytes:
    """Build FE-C page 50 (0x32) simulation wind resistance command."""
    if wind_resistance_coefficient is None:
        coefficient_raw = 0xFF
    else:
        if not 0 <= wind_resistance_coefficient <= 1.86:
            raise ValueError("Wind resistance coefficient must be 0..1.86 kg/m")
        coefficient_raw = int(round(wind_resistance_coefficient / 0.01))
    if wind_speed_kmh is None:
        wind_raw = 0xFF
    else:
        if not -127 <= wind_speed_kmh <= 127:
            raise ValueError("Wind speed must be -127..127 km/h")
        wind_raw = int(round(wind_speed_kmh + 127))
    if drafting_factor is None:
        drafting_raw = 0xFF
    else:
        if not 0 <= drafting_factor <= 1.0:
            raise ValueError("Drafting factor must be 0..1.0")
        drafting_raw = int(round(drafting_factor / 0.01))
    return bytes((0x32, 0xFF, 0xFF, 0xFF, 0xFF, coefficient_raw, wind_raw, drafting_raw))


def fe_track_resistance_payload(
    *,
    grade_percent: float | None = None,
    rolling_resistance_coefficient: float | None = None,
) -> bytes:
    """Build FE-C page 51 (0x33) simulation track resistance command."""
    if grade_percent is None:
        grade_raw = 0xFFFF
    else:
        if not -200 <= grade_percent <= 200:
            raise ValueError("Grade must be -200..200 %")
        grade_raw = int(round((grade_percent + 200.0) / 0.01))
    if rolling_resistance_coefficient is None:
        rolling_raw = 0xFF
    else:
        if not 0 <= rolling_resistance_coefficient <= 0.0127:
            raise ValueError("Rolling resistance coefficient must be 0..0.0127")
        rolling_raw = int(round(rolling_resistance_coefficient / 0.00005))
    return bytes((
        0x33, 0xFF, 0xFF, 0xFF, 0xFF,
        grade_raw & 0xFF, (grade_raw >> 8) & 0xFF, rolling_raw & 0xFF,
    ))


def fe_user_configuration_payload(
    *,
    user_weight_kg: float | None = None,
    bicycle_weight_kg: float | None = None,
    wheel_diameter_m: float | None = None,
    gear_ratio: float | None = None,
) -> bytes:
    """Build FE-C page 55 (0x37) user configuration for simulation mode."""
    if user_weight_kg is None:
        user_raw = 0xFFFF
    else:
        if not 0 <= user_weight_kg <= 655.34:
            raise ValueError("User weight must be 0..655.34 kg")
        user_raw = int(round(user_weight_kg / 0.01))

    if bicycle_weight_kg is None:
        bike_raw = 0xFFF
    else:
        if not 0 <= bicycle_weight_kg <= 50:
            raise ValueError("Bicycle weight must be 0..50 kg")
        bike_raw = int(round(bicycle_weight_kg / 0.05))

    if wheel_diameter_m is None:
        wheel_raw = 0xFF
        wheel_offset = 0x0F
    else:
        if not 0 <= wheel_diameter_m <= 2.54:
            raise ValueError("Wheel diameter must be 0..2.54 m")
        millimetres = int(round(wheel_diameter_m * 1000))
        wheel_raw = min(millimetres // 10, 0xFE)
        wheel_offset = millimetres - (wheel_raw * 10)
        if wheel_offset > 10:
            wheel_offset = 10

    if gear_ratio is None:
        gear_raw = 0x00
    else:
        if not 0.03 <= gear_ratio <= 7.65:
            raise ValueError("Gear ratio must be 0.03..7.65")
        gear_raw = int(round(gear_ratio / 0.03))

    packed_weight = ((wheel_offset & 0x0F) << 4) | (bike_raw & 0x0F)
    return bytes((
        0x37,
        user_raw & 0xFF, (user_raw >> 8) & 0xFF,
        0xFF,
        packed_weight, (bike_raw >> 4) & 0xFF,
        wheel_raw & 0xFF, gear_raw & 0xFF,
    ))


def fe_calibration_payload(*, zero_offset: bool = False, spin_down: bool = False) -> bytes:
    """Build FE-C page 1 calibration request; both False cancels calibration."""
    request = (0x40 if zero_offset else 0) | (0x80 if spin_down else 0)
    return bytes((0x01, request, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF))


def bicycle_power_manual_calibration_payload() -> bytes:
    """Build Bicycle Power page 1 manual-zero calibration request."""
    return bytes((0x01, 0xAA, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF))


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
