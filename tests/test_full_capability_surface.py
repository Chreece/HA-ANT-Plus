from pathlib import Path


def test_openant_bridge_does_not_suppress_profile_status():
    text = Path('custom_components/antplus/openant_bridge.py').read_text()
    assert 'is_battery_page = page_name == "battery"' in text
    assert '"status"' not in text.split('diagnostic_fields = {',1)[1].split('}',1)[0]


def test_tpms_controls_are_exposed():
    text = Path('custom_components/antplus/number.py').read_text()
    assert 'AntTpmsBarometricPressure' in text
    assert 'AntTpmsLowPressureAlarm' in text
    assert 'AntTpmsHighPressureAlarm' in text


def test_tpms_transport_profile_registered():
    text = Path('custom_components/antplus/control.py').read_text()
    assert 'DEVICE_TYPE_TIRE_PRESSURE: 8192' in text
    assert 'def tpms_parameter_payload' in text
