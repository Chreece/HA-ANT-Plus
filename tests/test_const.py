from custom_components.antplus.const import (
    DEFAULT_INACTIVITY_TIMEOUT,
    DEVICE_INACTIVITY_TIMEOUT,
    DOMAIN,
    device_display_name,
)
from custom_components.antplus.models import AntDevice


def test_domain_and_timeouts():
    assert DOMAIN == "antplus"
    assert DEFAULT_INACTIVITY_TIMEOUT == 30
    assert DEVICE_INACTIVITY_TIMEOUT == 60


def test_display_name_known_profile_and_manufacturer():
    device = AntDevice(device_id=12345)
    device.profiles.add(120)
    device.manufacturer_name = "Garmin"
    assert device_display_name(device) == "Garmin Heart Rate 12345"
