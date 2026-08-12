from custom_components.antplus.capabilities import (
    CONTROL_POWER_CALIBRATION,
    is_running_power_source,
    supports_bicycle_power_calibration,
    supports_control,
)
from custom_components.antplus.const import (
    DEVICE_TYPE_BIKE_CADENCE,
    DEVICE_TYPE_POWER,
    DEVICE_TYPE_RUNNING_DYNAMICS,
    DEVICE_TYPE_STRIDE_SPEED,
)
from custom_components.antplus.models import AntDevice


def _device(*profiles: int) -> AntDevice:
    device = AntDevice(device_id=37280)
    device.profiles.update(profiles)
    return device


def test_power_only_device_retains_bicycle_power_calibration():
    device = _device(DEVICE_TYPE_POWER)
    assert not is_running_power_source(device)
    assert supports_bicycle_power_calibration(device)
    assert supports_control(device, CONTROL_POWER_CALIBRATION)


def test_running_power_multi_profile_suppresses_bicycle_calibration():
    device = _device(DEVICE_TYPE_POWER, DEVICE_TYPE_RUNNING_DYNAMICS, DEVICE_TYPE_STRIDE_SPEED)
    assert is_running_power_source(device)
    assert not supports_bicycle_power_calibration(device)


def test_explicit_cycling_companion_retains_bicycle_calibration():
    device = _device(DEVICE_TYPE_POWER, DEVICE_TYPE_RUNNING_DYNAMICS, DEVICE_TYPE_BIKE_CADENCE)
    assert not is_running_power_source(device)
    assert supports_bicycle_power_calibration(device)


def test_button_creation_waits_for_profile_settle_window_and_uses_central_model():
    text = open("custom_components/antplus/button.py", encoding="utf-8").read()
    assert "hass.loop.call_later(5.0, finalize_power_controls" in text
    assert "supports_control(device, CONTROL_POWER_CALIBRATION)" in text
    assert "supports_control(self.ant_device, self.capability)" in text
