"""ANT+ packet decoders.

Every profile is retained. Known standard pages are decoded into native Home
Assistant metrics; unsupported pages are still exposed as disabled-by-default
raw diagnostic entities so no discovered ANT+ profile is silently discarded.
"""

from __future__ import annotations
from homeassistant.helpers.entity import EntityCategory

from math import isfinite
from datetime import datetime, timezone

from .const import (
    BATTERY_STATUS_NAMES,
    DEVICE_TYPE_BIKE_CADENCE,
    DEVICE_TYPE_BIKE_SPEED,
    DEVICE_TYPE_BIKE_SPEED_CADENCE,
    DEVICE_TYPE_FITNESS_EQUIPMENT,
    DEVICE_TYPE_HEART_RATE,
    DEVICE_TYPE_POWER,
    DEVICE_TYPE_SHIFTING,
    DEVICE_TYPE_STRIDE_SPEED,
)
from .models import AntDevice, AntMetric


def _metric(
    key: str,
    name: str,
    value,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    icon: str | None = None,
    entity_category: EntityCategory | None = None,
    enabled_default: bool = True,
    availability_mode: str = "metric",
) -> AntMetric:
    return AntMetric(
        key=key,
        name=name,
        value=value,
        unit=unit,
        device_class=device_class,
        state_class=state_class,
        icon=icon,
        entity_category=entity_category,
        enabled_default=enabled_default,
        updated_at=datetime.now(timezone.utc),
        availability_mode=availability_mode,
    )


def decode_native_packet(
    device: AntDevice, device_type: int, payload: bytes
) -> list[AntMetric]:
    """Decode one packet with HA ANT+'s native/documented backend."""
    if len(payload) != 8:
        return []

    page = payload[0] & 0x7F
    metrics: list[AntMetric] = [
        # Keep raw diagnostics bounded: one raw entity per device/profile.
        _metric(
            f"profile_{device_type}_raw",
            f"{_profile_label(device_type)} Raw Data",
            f"page={page} " + " ".join(f"{byte:02X}" for byte in payload),
            icon="mdi:code-brackets",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_default=False,
            availability_mode="device",
        ),
        _metric(
            f"profile_{device_type}_last_page",
            f"{_profile_label(device_type)} Last Data Page",
            page,
            icon="mdi:file-document-outline",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_default=False,
            availability_mode="device",
        ),
    ]

    # Common pages are only safe to decode for known standardized ANT+
    # device types. Proprietary profiles can reuse these page numbers.
    from .const import DEVICE_TYPE_NAMES
    if device_type in DEVICE_TYPE_NAMES and payload[0] in (80, 81, 82, 83):
        metrics.extend(_decode_common(payload))

    if device_type == DEVICE_TYPE_HEART_RATE:
        metrics.extend(_decode_heart_rate(payload))
    elif device_type == DEVICE_TYPE_POWER:
        metrics.extend(_decode_power(device, payload))
    elif device_type == DEVICE_TYPE_FITNESS_EQUIPMENT:
        metrics.extend(_decode_fitness_equipment(device, payload))
    elif device_type == DEVICE_TYPE_BIKE_CADENCE:
        metrics.extend(_decode_bike_cadence(device, payload))
    elif device_type == DEVICE_TYPE_BIKE_SPEED:
        metrics.extend(_decode_bike_speed(device, payload))
    elif device_type == DEVICE_TYPE_BIKE_SPEED_CADENCE:
        metrics.extend(_decode_bike_speed_cadence(device, payload))
    elif device_type == DEVICE_TYPE_SHIFTING:
        metrics.extend(_decode_shifting(payload))
    elif device_type == DEVICE_TYPE_STRIDE_SPEED:
        metrics.extend(_decode_stride_speed(device, payload))

    return metrics



def decode_packet(
    device: AntDevice, device_type: int, payload: bytes
) -> list[AntMetric]:
    """Decode one ANT+ packet through both installed parser adapters."""
    from .decoder_adapters import decode_with_adapters
    return decode_with_adapters(device, device_type, payload)

def _profile_label(device_type: int) -> str:
    from .const import DEVICE_TYPE_NAMES
    return DEVICE_TYPE_NAMES.get(device_type, f"Profile {device_type}")


def _decode_common(data: bytes) -> list[AntMetric]:
    metrics: list[AntMetric] = []
    page = data[0] & 0x7F

    if page == 80:
        hardware_revision = data[3]
        manufacturer_id = data[4] | (data[5] << 8)
        model_number = data[6] | (data[7] << 8)
        if hardware_revision != 0xFF:
            metrics.append(_metric("hardware_revision", "Hardware Revision", hardware_revision, icon="mdi:chip", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"))
        if manufacturer_id != 0xFFFF:
            metrics.append(_metric("manufacturer_id", "Manufacturer ID", manufacturer_id, icon="mdi:factory", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"))
        if model_number != 0xFFFF:
            metrics.append(_metric("model_number", "Model Number", model_number, icon="mdi:information-outline", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"))

    elif page == 81:
        software_supplemental = data[2]
        software_main = data[3]
        serial_number = int.from_bytes(data[4:8], "little")
        if not (software_supplemental == 0xFF and software_main == 0xFF):
            software = str(software_main / 10) if software_supplemental == 0xFF else str((software_main * 100 + software_supplemental) / 1000)
            metrics.append(_metric("software_revision", "Software Revision", software, icon="mdi:code-tags", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"))
        if serial_number != 0xFFFFFFFF:
            metrics.append(_metric("serial_number", "Serial Number", serial_number, icon="mdi:identifier", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"))

    elif page == 82:
        # ANT+ Common Page 82 battery status. Not every device implements it.
        fractional = data[6] / 256.0
        coarse = data[7] & 0x0F
        voltage = coarse + fractional
        status = (data[7] & 0x70) >> 4

        battery_descriptor = data[2]
        if battery_descriptor != 0xFF:
            battery_id = (battery_descriptor & 0xF0) >> 4
            battery_count = battery_descriptor & 0x0F
            metrics.extend([
                _metric(
                    "battery_id", "Battery ID", battery_id,
                    icon="mdi:identifier",
                    entity_category=EntityCategory.DIAGNOSTIC,
                    enabled_default=False,
                    availability_mode="device",
                ),
                _metric(
                    "battery_count", "Battery Count", battery_count,
                    icon="mdi:battery-multiple",
                    entity_category=EntityCategory.DIAGNOSTIC,
                    enabled_default=False,
                    availability_mode="device",
                ),
            ])

        operating_time_resolution = 2 if data[7] & 0x80 else 16
        operating_time = int.from_bytes(data[3:5], "little") * operating_time_resolution
        metrics.append(
            _metric(
                "battery_operating_time",
                "Battery Operating Time",
                operating_time,
                "s",
                "duration",
                "total_increasing",
                "mdi:timer-outline",
                EntityCategory.DIAGNOSTIC,
                False,
                "device",
            )
        )

        # A coarse value of 0x0F means unavailable. A resulting voltage of
        # 0 V is also not a meaningful battery measurement, so don't create
        # the entity until we have a real value.
        if coarse != 0x0F and voltage > 0:
            metrics.append(
                _metric(
                    "battery_voltage",
                    "Battery Voltage",
                    round(voltage, 3),
                    "V",
                    "voltage",
                    "measurement",
                    "mdi:battery",
                    EntityCategory.DIAGNOSTIC,
                    availability_mode="device",
                )
            )

        status_name = BATTERY_STATUS_NAMES.get(status)
        if status_name not in (None, "Unknown"):
            metrics.append(
                _metric(
                    "battery_status",
                    "Battery Status",
                    status_name,
                    icon="mdi:battery-heart-variant",
                    entity_category=EntityCategory.DIAGNOSTIC,
                    availability_mode="device",
                )
            )

    elif page == 83:
        # ANT+ Common Page 83 date/time. Keep it diagnostic because it is
        # device-supplied clock information rather than a live measurement.
        second, minute, hour = data[2], data[3], data[4]
        day = data[5] & 0x1F
        month = data[6]
        year = data[7] + 2000
        try:
            device_time = datetime(
                year, month, day, hour, minute, second
            ).isoformat()
        except ValueError:
            device_time = None
        if device_time is not None:
            metrics.append(
                _metric(
                    "device_datetime",
                    "Device Date/Time",
                    device_time,
                    icon="mdi:clock-outline",
                    entity_category=EntityCategory.DIAGNOSTIC,
                    enabled_default=False,
                    availability_mode="device",
                )
            )

    return metrics


def _decode_heart_rate(data: bytes) -> list[AntMetric]:
    page = data[0] & 0x7F
    heart_rate = data[7]
    metrics: list[AntMetric] = []

    if heart_rate != 0xFF:
        metrics.append(
            _metric(
                "heart_rate", "Heart Rate", heart_rate, "bpm",
                "heart_rate", "measurement", "mdi:heart-pulse"
            )
        )

    beat_time = int.from_bytes(data[4:6], "little") / 1024.0
    beat_count = data[6]
    metrics.extend([
        _metric(
            "heart_beat_count", "Heart Beat Count", beat_count,
            icon="mdi:counter", entity_category=EntityCategory.DIAGNOSTIC,
            enabled_default=False,
        ),
        _metric(
            "heart_beat_time", "Heart Beat Time", round(beat_time, 3), "s",
            "duration", "measurement", "mdi:timer-outline",
            EntityCategory.DIAGNOSTIC, False,
        ),
    ])

    if page == 1:
        operating_time = int.from_bytes(data[1:4], "little") * 2
        metrics.append(
            _metric(
                "operating_time", "Operating Time", operating_time, "s",
                "duration", "total_increasing", "mdi:timer-outline",
                EntityCategory.DIAGNOSTIC, False,
            )
        )
    elif page == 2:
        manufacturer_id = data[1]
        serial = data[2] | (data[3] << 8)
        metrics.extend([
            _metric(
                "manufacturer_id", "Manufacturer ID", manufacturer_id,
                icon="mdi:factory", entity_category=EntityCategory.DIAGNOSTIC,
                enabled_default=False,
            ),
            _metric(
                "device_serial_fragment", "Device Serial Fragment", serial,
                icon="mdi:identifier", entity_category=EntityCategory.DIAGNOSTIC,
                enabled_default=False,
            ),
        ])
    elif page == 3:
        metrics.extend([
            _metric(
                "hardware_revision", "Hardware Revision", data[1],
                icon="mdi:chip", entity_category=EntityCategory.DIAGNOSTIC,
                enabled_default=False,
            ),
            _metric(
                "software_revision", "Software Revision", data[2],
                icon="mdi:code-tags", entity_category=EntityCategory.DIAGNOSTIC,
                enabled_default=False,
            ),
            _metric(
                "model_number", "Model Number", data[3],
                icon="mdi:information-outline", entity_category=EntityCategory.DIAGNOSTIC,
                enabled_default=False,
            ),
        ])
    elif page == 7:
        # ANT+ HRM Data Page 7: battery percentage, fractional voltage,
        # and coarse voltage/status in the descriptive bit field.
        battery_level = data[1]
        fractional = data[2] / 256.0
        descriptive = data[3]
        coarse = descriptive & 0x0F
        status = (descriptive & 0x70) >> 4

        if battery_level <= 100:
            metrics.append(
                _metric(
                    "battery_level",
                    "Battery",
                    battery_level,
                    "%",
                    "battery",
                    "measurement",
                    "mdi:battery",
                    availability_mode="device",
                )
            )

        voltage = coarse + fractional
        if coarse != 0x0F and voltage > 0:
            metrics.append(
                _metric(
                    "battery_voltage",
                    "Battery Voltage",
                    round(voltage, 3),
                    "V",
                    "voltage",
                    "measurement",
                    "mdi:battery",
                    EntityCategory.DIAGNOSTIC,
                    availability_mode="device",
                )
            )

        status_name = BATTERY_STATUS_NAMES.get(status)
        if status_name not in (None, "Unknown"):
            metrics.append(
                _metric(
                    "battery_status",
                    "Battery Status",
                    status_name,
                    icon="mdi:battery-heart-variant",
                    entity_category=EntityCategory.DIAGNOSTIC,
                    availability_mode="device",
                )
            )

    return metrics


def _decode_power(device: AntDevice, data: bytes) -> list[AntMetric]:
    page = data[0] & 0x7F
    metrics: list[AntMetric] = []

    if page == 0x10:
        event_count = data[1]
        pedal_power = data[2]
        cadence = data[3]
        accumulated_power = int.from_bytes(data[4:6], "little")
        instantaneous_power = int.from_bytes(data[6:8], "little")

        if cadence != 0xFF:
            metrics.append(
                _metric(
                    "cadence", "Cadence", cadence, "rpm",
                    state_class="measurement", icon="mdi:rotate-right"
                )
            )

        if instantaneous_power != 0xFFFF:
            metrics.append(
                _metric(
                    "power", "Power", instantaneous_power, "W",
                    "power", "measurement", "mdi:flash"
                )
            )

            # Bit 7 means pedal-power contribution is the right side.
            if pedal_power != 0xFF and pedal_power & 0x80:
                right_pct = pedal_power & 0x7F
                right = instantaneous_power * right_pct / 100.0
                left = instantaneous_power - right
                metrics.extend([
                    _metric(
                        "right_power", "Right Power", round(right, 1), "W",
                        "power", "measurement", "mdi:flash"
                    ),
                    _metric(
                        "left_power", "Left Power", round(left, 1), "W",
                        "power", "measurement", "mdi:flash"
                    ),
                    _metric(
                        "right_power_balance", "Right Power Balance",
                        right_pct, "%", state_class="measurement",
                        icon="mdi:scale-balance"
                    ),
                ])

        state = device.decoder_state.setdefault("power", {})
        old_count = state.get("event_count")
        old_acc = state.get("accumulated_power")
        if old_count is not None and old_acc is not None:
            delta_count = (event_count - old_count) & 0xFF
            if delta_count:
                delta_power = (accumulated_power - old_acc) & 0xFFFF
                metrics.append(
                    _metric(
                        "average_power", "Average Power",
                        round(delta_power / delta_count, 1), "W",
                        "power", "measurement", "mdi:flash-outline"
                    )
                )
        state["event_count"] = event_count
        state["accumulated_power"] = accumulated_power

    elif page == 0x12:
        # Crank torque frequency / standard torque page, as implemented
        # by OpenANT's PowerMeter parser.
        event_count = data[1]
        crank_ticks = data[2]
        cadence = data[3]
        crank_period = int.from_bytes(data[4:6], "little")
        accumulated_torque = int.from_bytes(data[6:8], "little")

        if cadence != 0xFF:
            metrics.append(
                _metric(
                    "cadence", "Cadence", cadence, "rpm",
                    state_class="measurement", icon="mdi:rotate-right"
                )
            )

        state = device.decoder_state.setdefault("power_torque", {})
        if all(k in state for k in ("event_count", "crank_period", "torque")):
            delta_events = (event_count - state["event_count"]) & 0xFF
            delta_period = (crank_period - state["crank_period"]) & 0xFFFF
            delta_torque = (accumulated_torque - state["torque"]) & 0xFFFF

            if delta_events:
                torque_nm = delta_torque / (32.0 * delta_events)
                metrics.append(
                    _metric(
                        "torque", "Torque", round(torque_nm, 2), "N·m",
                        state_class="measurement", icon="mdi:rotate-orbit"
                    )
                )

                if delta_period:
                    angular_velocity = (
                        2.0 * 3.141592653589793 * delta_events
                    ) / (delta_period / 2048.0)
                    metrics.extend([
                        _metric(
                            "angular_velocity", "Angular Velocity",
                            round(angular_velocity, 2), "rad/s",
                            state_class="measurement",
                            icon="mdi:rotate-orbit"
                        ),
                        _metric(
                            "average_power", "Average Power",
                            round(torque_nm * angular_velocity, 1), "W",
                            "power", "measurement",
                            "mdi:flash-outline"
                        ),
                    ])

        state["event_count"] = event_count
        state["crank_ticks"] = crank_ticks
        state["crank_period"] = crank_period
        state["torque"] = accumulated_torque

    return metrics

def _decode_fitness_equipment(device: AntDevice, data: bytes) -> list[AntMetric]:
    page = data[0] & 0x7F
    metrics: list[AntMetric] = []

    if page == 0x01:
        response = data[1]
        metrics.extend([
            _metric("calibration_zero_offset_status", "Zero Offset Calibration Status", "success" if response & 0x40 else "not_requested_or_failed", icon="mdi:scale-balance", entity_category=EntityCategory.DIAGNOSTIC),
            _metric("calibration_spin_down_status", "Spin Down Calibration Status", "success" if response & 0x80 else "not_requested_or_failed", icon="mdi:rotate-360", entity_category=EntityCategory.DIAGNOSTIC),
        ])
        if data[3] != 0xFF:
            metrics.append(_metric("calibration_temperature", "Calibration Temperature", round((data[3] * 0.5) - 25.0, 1), "°C", "temperature", "measurement", "mdi:thermometer", EntityCategory.DIAGNOSTIC))
        zero_offset = int.from_bytes(data[4:6], "little")
        if zero_offset != 0xFFFF:
            metrics.append(_metric("calibration_zero_offset", "Calibration Zero Offset", zero_offset, icon="mdi:counter", entity_category=EntityCategory.DIAGNOSTIC))
        spin_down = int.from_bytes(data[6:8], "little")
        if spin_down != 0xFFFF:
            metrics.append(_metric("calibration_spin_down_time", "Calibration Spin Down Time", spin_down, "ms", state_class="measurement", icon="mdi:timer-outline", entity_category=EntityCategory.DIAGNOSTIC))
    elif page == 0x02:
        metrics.extend([
            _metric("calibration_zero_offset_pending", "Zero Offset Calibration Pending", bool(data[1] & 0x40), icon="mdi:progress-wrench", entity_category=EntityCategory.DIAGNOSTIC),
            _metric("calibration_spin_down_pending", "Spin Down Calibration Pending", bool(data[1] & 0x80), icon="mdi:progress-wrench", entity_category=EntityCategory.DIAGNOSTIC),
        ])
        if data[3] != 0xFF:
            metrics.append(_metric("calibration_current_temperature", "Calibration Current Temperature", round((data[3] * 0.5) - 25.0, 1), "°C", "temperature", "measurement", "mdi:thermometer", EntityCategory.DIAGNOSTIC))
        target_speed = int.from_bytes(data[4:6], "little")
        if target_speed != 0xFFFF:
            metrics.append(_metric("calibration_target_speed", "Calibration Target Speed", round(target_speed / 1000.0, 3), "m/s", "speed", "measurement", "mdi:speedometer", EntityCategory.DIAGNOSTIC))
        target_time = int.from_bytes(data[6:8], "little")
        if target_time != 0xFFFF:
            metrics.append(_metric("calibration_target_spin_down_time", "Calibration Target Spin Down Time", target_time, "ms", state_class="measurement", icon="mdi:timer-outline", entity_category=EntityCategory.DIAGNOSTIC))
    elif page == 0x10:
        speed = int.from_bytes(data[4:6], "little") / 1000.0
        if speed < 65.535:
            metrics.extend([
                _metric(
                    "speed", "Speed", round(speed, 3), "m/s",
                    "speed", "measurement", "mdi:speedometer"
                ),
                _pace_metric(speed),
            ])
    elif page == 0x11:
        incline_raw = int.from_bytes(data[4:6], "little", signed=False)
        if incline_raw != 0x7FFF:
            if incline_raw >= 0x8000:
                incline_raw -= 0x10000
            metrics.append(
                _metric(
                    "incline", "Incline", round(incline_raw / 100.0, 2), "%",
                    state_class="measurement", icon="mdi:slope-uphill"
                )
            )
        if data[6] != 0xFF:
            metrics.append(
                _metric(
                    "resistance", "Resistance", round(data[6] / 2.0, 1), "%",
                    state_class="measurement", icon="mdi:gauge"
                )
            )
    elif page == 0x19:
        cadence = data[2]
        power = data[5] | ((data[6] & 0x0F) << 8)
        if cadence != 0xFF:
            metrics.append(
                _metric(
                    "cadence", "Cadence", cadence, "rpm",
                    state_class="measurement", icon="mdi:rotate-right"
                )
            )
        if power != 0xFFF:
            metrics.append(
                _metric(
                    "power", "Power", power, "W",
                    "power", "measurement", "mdi:flash"
                )
            )
    elif page == 0x32:
        if data[5] != 0xFF:
            metrics.append(_metric("simulation_wind_resistance", "Simulation Wind Resistance Coefficient", round(data[5] * 0.01, 2), "kg/m", state_class="measurement", icon="mdi:weather-windy"))
        if data[6] != 0xFF:
            metrics.append(_metric("simulation_wind_speed", "Simulation Wind Speed", data[6] - 127, "km/h", "speed", "measurement", "mdi:weather-windy"))
        if data[7] != 0xFF:
            metrics.append(_metric("simulation_drafting_factor", "Simulation Drafting Factor", round(data[7] * 0.01, 2), state_class="measurement", icon="mdi:account-multiple"))
    elif page == 0x33:
        grade_raw = int.from_bytes(data[5:7], "little")
        if grade_raw != 0xFFFF:
            metrics.append(_metric("simulation_grade", "Simulation Grade", round((grade_raw * 0.01) - 200.0, 2), "%", state_class="measurement", icon="mdi:slope-uphill"))
        if data[7] != 0xFF:
            metrics.append(_metric("simulation_rolling_resistance", "Simulation Rolling Resistance Coefficient", round(data[7] * 0.00005, 5), state_class="measurement", icon="mdi:road-variant"))
    elif page == 0x36:
        maximum = int.from_bytes(data[5:7], "little")
        if maximum != 0xFFFF:
            metrics.append(_metric("maximum_resistance", "Maximum Resistance", maximum, "N", state_class="measurement", icon="mdi:gauge"))
        capabilities = data[7]
        device.decoder_state["fe_capabilities"] = {
            "basic_resistance": bool(capabilities & 0x01),
            "target_power": bool(capabilities & 0x02),
            "simulation": bool(capabilities & 0x04),
        }
        metrics.extend([
            _metric("supports_basic_resistance", "Supports Basic Resistance", bool(capabilities & 0x01), icon="mdi:gauge", entity_category=EntityCategory.DIAGNOSTIC),
            _metric("supports_target_power", "Supports Target Power", bool(capabilities & 0x02), icon="mdi:flash", entity_category=EntityCategory.DIAGNOSTIC),
            _metric("supports_simulation", "Supports Simulation", bool(capabilities & 0x04), icon="mdi:slope-uphill", entity_category=EntityCategory.DIAGNOSTIC),
        ])
    elif page == 0x37:
        user_raw = int.from_bytes(data[1:3], "little")
        if user_raw != 0xFFFF:
            metrics.append(_metric("configured_user_weight", "Configured User Weight", round(user_raw * 0.01, 2), "kg", "weight", "measurement", "mdi:weight"))
        wheel_offset = (data[4] >> 4) & 0x0F
        bike_raw = (data[4] & 0x0F) | (data[5] << 4)
        if bike_raw != 0xFFF:
            metrics.append(_metric("configured_bicycle_weight", "Configured Bicycle Weight", round(bike_raw * 0.05, 2), "kg", "weight", "measurement", "mdi:bike"))
        if data[6] != 0xFF:
            diameter = data[6] * 0.01 + (0 if wheel_offset == 0x0F else wheel_offset * 0.001)
            metrics.append(_metric("configured_wheel_diameter", "Configured Wheel Diameter", round(diameter, 3), "m", state_class="measurement", icon="mdi:circle-outline"))
        if data[7] != 0:
            metrics.append(_metric("configured_gear_ratio", "Configured Gear Ratio", round(data[7] * 0.03, 2), state_class="measurement", icon="mdi:cog"))
    elif page == 0x47:
        command_id = data[1]
        status_raw = data[3]
        status_name = {
            0: "Pass",
            1: "Fail",
            2: "Not Supported",
            3: "Rejected",
            4: "Pending",
            255: "Uninitialized",
        }.get(status_raw, f"Unknown ({status_raw})")
        metrics.extend([
            _metric("last_command_id", "Last Command ID", command_id, icon="mdi:identifier", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False),
            _metric("command_status", "Command Status", status_name, icon="mdi:check-decagram-outline", entity_category=EntityCategory.DIAGNOSTIC),
        ])
        if command_id == 0x30 and data[7] != 0xFF:
            metrics.append(_metric("confirmed_basic_resistance", "Confirmed Basic Resistance", round(data[7] / 2.0, 1), "%", state_class="measurement", icon="mdi:gauge", entity_category=EntityCategory.DIAGNOSTIC))
        elif command_id == 0x31:
            raw_power = int.from_bytes(data[6:8], "little")
            if raw_power != 0xFFFF:
                metrics.append(_metric("confirmed_target_power", "Confirmed Target Power", round(raw_power / 4.0, 2), "W", "power", "measurement", "mdi:flash", EntityCategory.DIAGNOSTIC))

    return [m for m in metrics if m is not None]


def _update_revolution_metric(
    device: AntDevice,
    state_key: str,
    event_time_raw: int,
    revolution_count: int,
    *,
    cadence: bool,
) -> list[AntMetric]:
    state = device.decoder_state.setdefault(state_key, {})
    old_time = state.get("time")
    old_rev = state.get("rev")
    state["time"] = event_time_raw
    state["rev"] = revolution_count
    if old_time is None or old_rev is None:
        return []

    delta_time = (event_time_raw - old_time) & 0xFFFF
    delta_rev = (revolution_count - old_rev) & 0xFFFF
    if delta_time == 0:
        return []

    seconds = delta_time / 1024.0
    if cadence:
        rpm = 60.0 * delta_rev / seconds
        return [
            _metric(
                "cadence", "Cadence", round(rpm, 1), "rpm",
                state_class="measurement", icon="mdi:rotate-right"
            )
        ]
    # Wheel circumference is user-specific, so expose wheel RPM universally.
    rpm = 60.0 * delta_rev / seconds
    return [
        _metric(
            "wheel_rpm", "Wheel RPM", round(rpm, 1), "rpm",
            state_class="measurement", icon="mdi:bike"
        ),
        _metric(
            "wheel_revolutions", "Wheel Revolutions", revolution_count,
            state_class="total_increasing", icon="mdi:counter",
            enabled_default=False,
        ),
    ]


def _decode_bike_cadence(device: AntDevice, data: bytes) -> list[AntMetric]:
    if (data[0] & 0x0F) > 7:
        return []
    return _update_revolution_metric(
        device, "bike_cadence",
        int.from_bytes(data[4:6], "little"),
        int.from_bytes(data[6:8], "little"),
        cadence=True,
    )


def _decode_bike_speed(device: AntDevice, data: bytes) -> list[AntMetric]:
    if (data[0] & 0x0F) > 7:
        return []
    return _update_revolution_metric(
        device, "bike_speed",
        int.from_bytes(data[4:6], "little"),
        int.from_bytes(data[6:8], "little"),
        cadence=False,
    )


def _decode_bike_speed_cadence(device: AntDevice, data: bytes) -> list[AntMetric]:
    metrics = []
    metrics.extend(
        _update_revolution_metric(
            device, "bike_sc_cadence",
            int.from_bytes(data[0:2], "little"),
            int.from_bytes(data[2:4], "little"),
            cadence=True,
        )
    )
    metrics.extend(
        _update_revolution_metric(
            device, "bike_sc_speed",
            int.from_bytes(data[4:6], "little"),
            int.from_bytes(data[6:8], "little"),
            cadence=False,
        )
    )
    return metrics




def _decode_shifting(data: bytes) -> list[AntMetric]:
    """Decode validated ANT+ Shifting status and trim pages."""
    page = data[0] & 0x7F
    metrics: list[AntMetric] = []

    if page == 0x01:
        rear = data[3] & 0x1F
        front = (data[3] & 0xE0) >> 5
        total_rear = data[4] & 0x1F
        total_front = (data[4] & 0xE0) >> 5
        metrics.extend([
            _metric("rear_gear", "Rear Gear", rear, icon="mdi:cog"),
            _metric("front_gear", "Front Gear", front, icon="mdi:cog-outline"),
            _metric("rear_gear_count", "Rear Gear Count", total_rear, icon="mdi:counter", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"),
            _metric("front_gear_count", "Front Gear Count", total_front, icon="mdi:counter", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"),
            _metric("shift_event_count", "Shift Event Count", data[1], icon="mdi:counter", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"),
        ])
        diagnostic_values = (
            ("invalid_rear_inboard_shifts", "Invalid Rear Inboard Shifts", data[5] & 0x0F),
            ("invalid_rear_outboard_shifts", "Invalid Rear Outboard Shifts", (data[5] & 0xF0) >> 4),
            ("invalid_front_inboard_shifts", "Invalid Front Inboard Shifts", data[6] & 0x0F),
            ("invalid_front_outboard_shifts", "Invalid Front Outboard Shifts", (data[6] & 0xF0) >> 4),
            ("rear_shift_failures", "Rear Shift Failures", data[7] & 0x0F),
            ("front_shift_failures", "Front Shift Failures", (data[7] & 0xF0) >> 4),
        )
        for key, name, value in diagnostic_values:
            metrics.append(_metric(key, name, value, icon="mdi:alert-circle-outline", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"))

    elif page == 0x04:
        metrics.extend([
            _metric("rear_trim", "Rear Trim", data[4], icon="mdi:tune-variant"),
            _metric("front_trim", "Front Trim", data[5], icon="mdi:tune"),
            _metric("rear_trim_max", "Rear Trim Maximum", data[2], icon="mdi:tune-variant", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"),
            _metric("front_trim_max", "Front Trim Maximum", data[3], icon="mdi:tune", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=False, availability_mode="device"),
        ])

    return metrics

def _decode_stride_speed(device: AntDevice, data: bytes) -> list[AntMetric]:
    """Decode ANT+ Stride Based Speed & Distance (device type 124).

    Page 1 carries time, distance, speed, stride count and update latency.
    Pages 2-15 carry cadence, speed and status; page 3 also carries calories.
    """
    page = data[0] & 0x7F
    metrics: list[AntMetric] = []

    if page == 1:
        time_fractional = data[1]
        time_integer = data[2]
        distance_integer = data[3]
        distance_fractional = data[4] >> 4
        speed_integer = data[4] & 0x0F
        speed_fractional = data[5]
        stride_count_raw = data[6]
        update_latency_raw = data[7]

        speed = speed_integer + speed_fractional / 256.0
        distance_raw = distance_integer + distance_fractional / 16.0

        metrics.append(
            _metric(
                "speed",
                "Speed",
                round(speed, 3),
                "m/s",
                "speed",
                "measurement",
                "mdi:speedometer",
            )
        )
        pace = _pace_metric(speed)
        if pace is not None:
            metrics.append(pace)

        # The page-1 distance and stride fields roll over. Maintain totals
        # since this receiver first observed the device rather than exposing
        # misleading 8-bit rolling values as total_increasing sensors.
        state = device.decoder_state.setdefault("sdm", {})

        prev_distance = state.get("distance_raw")
        total_distance = state.get("distance_total", 0.0)
        if prev_distance is not None:
            delta_distance = distance_raw - prev_distance
            if delta_distance < 0:
                delta_distance += 256.0
            # Ignore implausible re-sync jumps.
            if 0 <= delta_distance < 50:
                total_distance += delta_distance
        state["distance_raw"] = distance_raw
        state["distance_total"] = total_distance

        metrics.append(
            _metric(
                "distance",
                "Distance",
                round(total_distance, 2),
                "m",
                "distance",
                "total_increasing",
                "mdi:map-marker-distance",
            )
        )

        prev_stride = state.get("stride_raw")
        total_strides = state.get("stride_total", 0)
        if prev_stride is not None:
            delta_stride = (stride_count_raw - prev_stride) & 0xFF
            if delta_stride < 100:
                total_strides += delta_stride
        state["stride_raw"] = stride_count_raw
        state["stride_total"] = total_strides

        metrics.append(
            _metric(
                "stride_count",
                "Stride Count",
                total_strides,
                state_class="total_increasing",
                icon="mdi:run",
            )
        )

        metrics.extend(
            [
                _metric(
                    "sdm_time",
                    "SDM Time",
                    round(time_integer + time_fractional / 200.0, 3),
                    "s",
                    "duration",
                    "measurement",
                    "mdi:timer-outline",
                    EntityCategory.DIAGNOSTIC,
                    False,
                ),
                _metric(
                    "update_latency",
                    "Update Latency",
                    round(update_latency_raw / 32.0, 3),
                    "s",
                    "duration",
                    "measurement",
                    "mdi:timer-sand",
                    EntityCategory.DIAGNOSTIC,
                    False,
                ),
            ]
        )

    elif 2 <= page <= 15:
        cadence_integer = data[3]
        cadence_fractional = data[4] >> 4
        speed_integer = data[4] & 0x0F
        speed_fractional = data[5]
        status = data[7]

        speed = speed_integer + speed_fractional / 256.0
        cadence = cadence_integer + cadence_fractional / 16.0

        metrics.append(
            _metric(
                "speed",
                "Speed",
                round(speed, 3),
                "m/s",
                "speed",
                "measurement",
                "mdi:speedometer",
            )
        )
        pace = _pace_metric(speed)
        if pace is not None:
            metrics.append(pace)

        # Keep SDM cadence separate from power-profile cadence because some
        # running sensors define/scale these differently.
        if cadence_integer != 0xFF:
            metrics.append(
                _metric(
                    "stride_cadence",
                    "Stride Cadence",
                    round(cadence, 1),
                    "spm",
                    state_class="measurement",
                    icon="mdi:run-fast",
                )
            )

        metrics.append(
            _metric(
                "sdm_status",
                "SDM Status",
                status,
                icon="mdi:information-outline",
                entity_category=EntityCategory.DIAGNOSTIC,
                enabled_default=False,
            )
        )

        if page == 3 and data[6] != 0xFF:
            metrics.append(
                _metric(
                    "calories",
                    "Calories",
                    data[6],
                    "kcal",
                    state_class="measurement",
                    icon="mdi:fire",
                )
            )

    return metrics


def _pace_metric(speed_m_s: float) -> AntMetric:
    # Below 0.2 m/s (~18:20 min/km), pace is not meaningful. Emit an
    # explicit None value so Home Assistant immediately displays "unknown"
    # instead of retaining the previous running pace until inactivity.
    if speed_m_s < 0.2 or not isfinite(speed_m_s):
        return _metric(
            "pace",
            "Pace",
            None,
            "min/km",
            state_class="measurement",
            icon="mdi:run-fast",
        )

    pace_min_km = (1000.0 / speed_m_s) / 60.0
    return _metric(
        "pace",
        "Pace",
        round(pace_min_km, 2),
        "min/km",
        state_class="measurement",
        icon="mdi:run-fast",
    )
