from pathlib import Path

from custom_components.antplus.button import _is_raw_fallback_unique_id
from custom_components.antplus.const import DEVICE_TYPE_NAMES, PLATFORMS


def test_cleanup_button_platform_enabled():
    assert "button" in PLATFORMS


def test_raw_fallback_classifier():
    assert _is_raw_fallback_unique_id("14005_profile_69_last_page")
    assert _is_raw_fallback_unique_id("14005_profile_69_page_86_raw")
    assert not _is_raw_fallback_unique_id("9190_heart_rate")
    assert not _is_raw_fallback_unique_id("13059_battery_level")
    assert not _is_raw_fallback_unique_id("12345_speed")


def test_market_profile_catalogue():
    expected = {
        1: "Sync",
        11: "Power Meter",
        15: "Multi-Sport Speed/Distance",
        16: "Controls Device",
        17: "Fitness Equipment",
        18: "Blood Pressure",
        19: "Geocache",
        20: "Light Electric Vehicle",
        25: "Environment",
        26: "Racquet",
        30: "Running Dynamics",
        31: "Muscle Oxygen",
        34: "Shifting",
        35: "Bicycle Lights",
        40: "Radar",
        41: "Tracker",
        48: "Tire Pressure Monitor",
        115: "Dropper Seatpost",
        116: "Suspension",
        119: "Weight Scale",
        120: "Heart Rate",
        121: "Bike Speed/Cadence",
        122: "Bike Cadence",
        123: "Bike Speed",
        124: "Stride Speed/Distance",
        127: "Core Temperature",
    }
    for device_type, name in expected.items():
        assert DEVICE_TYPE_NAMES[device_type] == name


def test_extended_openant_bridge_is_defensive():
    source = Path("custom_components/antplus/openant_bridge.py").read_text()
    for module_name in (
        "blood_pressure",
        "racquet",
        "running_dynamics",
        "muscle_oxygen",
        "bike_light",
        "radar",
        "tracker",
        "suspension",
        "weight_scale",
    ):
        assert f"openant.devices.{module_name}" in source
    assert "except Exception:" in source
