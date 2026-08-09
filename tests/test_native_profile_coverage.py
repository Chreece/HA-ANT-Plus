from pathlib import Path

from custom_components.antplus.const import (
    DEVICE_TYPE_BLOOD_PRESSURE,
    DEVICE_TYPE_GEOCACHE,
    DEVICE_TYPE_MUSCLE_OXYGEN,
    DEVICE_TYPE_SHIFTING,
    DEVICE_TYPE_SYNC,
    DEVICE_TYPE_WEIGHT_SCALE,
)
from custom_components.antplus.decoder import decode_packet
from custom_components.antplus.models import AntDevice
from custom_components.antplus.profile_support import PROFILE_SUPPORT, native_profile_types


def _values(metrics):
    return {metric.key: metric.value for metric in metrics}


def test_native_shifting_page_1():
    device = AntDevice(device_id=36006)
    payload = bytes([0x01, 7, 0, (2 << 5) | 5, (2 << 5) | 12, (3 << 4) | 2, (4 << 4) | 1, (6 << 4) | 5])
    values = _values(decode_packet(device, DEVICE_TYPE_SHIFTING, payload))
    assert values["rear_gear"] == 5
    assert values["front_gear"] == 2
    assert values["rear_gear_count"] == 12
    assert values["front_gear_count"] == 2
    assert values["shift_event_count"] == 7
    assert values["invalid_rear_inboard_shifts"] == 2
    assert values["invalid_rear_outboard_shifts"] == 3
    assert values["invalid_front_inboard_shifts"] == 1
    assert values["invalid_front_outboard_shifts"] == 4
    assert values["rear_shift_failures"] == 5
    assert values["front_shift_failures"] == 6


def test_native_shifting_trim_page():
    device = AntDevice(device_id=36006)
    values = _values(decode_packet(device, DEVICE_TYPE_SHIFTING, bytes([0x04, 0, 11, 7, 5, 3, 0, 0])))
    assert values["rear_trim_max"] == 11
    assert values["front_trim_max"] == 7
    assert values["rear_trim"] == 5
    assert values["front_trim"] == 3


def test_shifting_is_native():
    assert DEVICE_TYPE_SHIFTING in native_profile_types()


def test_protocol_modes_are_truthful():
    assert PROFILE_SUPPORT[DEVICE_TYPE_BLOOD_PRESSURE].mode == "antfs"
    assert PROFILE_SUPPORT[DEVICE_TYPE_SYNC].mode == "antfs"
    assert PROFILE_SUPPORT[DEVICE_TYPE_GEOCACHE].mode == "active_protocol"
    assert PROFILE_SUPPORT[DEVICE_TYPE_WEIGHT_SCALE].mode == "spec_required"
    assert PROFILE_SUPPORT[DEVICE_TYPE_MUSCLE_OXYGEN].mode == "spec_required"


def test_nonexistent_openant_modules_removed():
    source = Path("custom_components/antplus/openant_bridge.py").read_text()
    for module in (
        "multi_sport_speed_distance", "blood_pressure", "geocache", "racquet",
        "running_dynamics", "muscle_oxygen", "bike_light", "radar", "tracker",
        "suspension", "weight_scale",
    ):
        assert f"openant.devices.{module}" not in source


def test_every_named_device_type_has_support_classification():
    from custom_components.antplus.const import DEVICE_TYPE_NAMES
    assert sorted(set(DEVICE_TYPE_NAMES) - set(PROFILE_SUPPORT)) == []
