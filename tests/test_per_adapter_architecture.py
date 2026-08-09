from pathlib import Path

from custom_components.antplus.adapter_sensor import _source_matches_adapter
from custom_components.antplus.receiver import AntPlusReceiver


def test_source_matching_is_per_physical_adapter():
    key = "0FCF:1008:123"
    assert _source_matches_adapter(f"local:{key}", key)
    assert _source_matches_adapter(f"remote:Gastezimmer:{key}", key)
    assert not _source_matches_adapter("local:0FCF:1008:456", key)


def test_same_ant_sensor_merges_across_multiple_usb_adapters():
    receiver = AntPlusReceiver()
    adapter_a = "0FCF:1008:123"
    adapter_b = "0FCF:1008:456"

    for _ in range(5):
        receiver.process_packet(
            device_id=9190,
            device_type=120,
            transmission_type=1,
            payload=bytes([0, 0, 0, 0, 0, 0, 0, 75]),
            source=f"local:{adapter_a}",
        )

    for _ in range(5):
        receiver.process_packet(
            device_id=9190,
            device_type=120,
            transmission_type=1,
            payload=bytes([0, 0, 0, 0, 0, 0, 0, 76]),
            source=f"remote:Bedroom:{adapter_b}",
        )

    assert list(receiver.devices) == [9190]
    sources = receiver.devices[9190].decoder_state["sources"]
    assert f"local:{adapter_a}" in sources
    assert f"remote:Bedroom:{adapter_b}" in sources


def test_cleanup_no_longer_lives_on_usb_adapters():
    source = Path("custom_components/antplus/button.py").read_text()

    assert "AntUsbAdapterCleanupStaleDevicesButton" not in source
    assert 'name="ANT+ Sensors"' in source
    assert "SENSORS_PARENT_IDENTIFIER" in source


def test_adapter_diagnostics_live_on_physical_adapter():
    source = Path("custom_components/antplus/adapter_sensor.py").read_text()
    for entity in (
        "AntUsbAdapterConnectionSensor",
        "AntUsbAdapterSensorsSeenSensor",
        "AntUsbAdapterLastErrorSensor",
        "AntUsbAdapterDecoderCoverageSensor",
    ):
        assert entity in source
    assert "identifiers={adapter.ha_identifier}" in source


def test_no_active_integration_device_model():
    const_source = Path("custom_components/antplus/const.py").read_text()
    button_source = Path("custom_components/antplus/button.py").read_text()
    sensor_source = Path("custom_components/antplus/sensor.py").read_text()
    assert "INTEGRATION_DEVICE_IDENTIFIER" not in const_source
    assert "INTEGRATION_DEVICE_IDENTIFIER" not in button_source
    assert "AntPlusIntegrationDiagnosticSensor" not in sensor_source
