from pathlib import Path

from custom_components.antplus.const import SENSORS_PARENT_IDENTIFIER
from custom_components.antplus.receiver import AntPlusReceiver


def test_sensor_parent_identifier():
    assert SENSORS_PARENT_IDENTIFIER == ("antplus", "sensors")


def test_each_ant_sensor_keeps_distinct_ha_identifier():
    source = Path("custom_components/antplus/entity.py").read_text()
    assert '"identifiers": {(DOMAIN, str(dev.device_id))}' in source
    assert '"via_device": SENSORS_PARENT_IDENTIFIER' in source


def test_same_sensor_from_multiple_adapters_remains_one_logical_device():
    receiver = AntPlusReceiver()

    for _ in range(5):
        receiver.process_packet(
            device_id=9190,
            device_type=120,
            transmission_type=1,
            payload=bytes([0, 0, 0, 0, 0, 0, 0, 75]),
            source="local:0FCF:1008:123",
        )

    for _ in range(5):
        receiver.process_packet(
            device_id=9190,
            device_type=120,
            transmission_type=1,
            payload=bytes([0, 0, 0, 0, 0, 0, 0, 76]),
            source="remote:Bedroom:0FCF:1008:456",
        )

    assert list(receiver.devices) == [9190]


def test_cleanup_button_lives_on_sensor_parent():
    source = Path("custom_components/antplus/button.py").read_text()
    assert 'identifiers={SENSORS_PARENT_IDENTIFIER}' in source
    assert 'name="ANT+ Sensors"' in source
    assert "AntUsbAdapterCleanupStaleDevicesButton" not in source


def test_usb_adapters_remain_top_level():
    for name in ("adapter.py", "adapter_sensor.py", "switch.py"):
        path = Path("custom_components/antplus") / name
        if not path.exists():
            continue
        text = path.read_text()
        assert "SENSORS_PARENT_IDENTIFIER" not in text


def test_parent_registered_on_setup():
    source = Path("custom_components/antplus/__init__.py").read_text()
    assert "identifiers={SENSORS_PARENT_IDENTIFIER}" in source
    assert 'name="ANT+ Sensors"' in source
    assert "via_device_id=sensor_parent.id" in source
