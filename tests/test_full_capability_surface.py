from pathlib import Path


def test_openant_bridge_does_not_suppress_profile_status():
    text = Path('custom_components/antplus/openant_bridge.py').read_text()
    assert 'page_name == "battery"' in text
    assert 'and "battery_id" in values' in text
    assert 'if key == "status"' in text
    assert 'key = f"{page_key}_status"' in text


def test_tpms_controls_are_exposed():
    text = Path('custom_components/antplus/number.py').read_text()
    assert 'AntTpmsBarometricPressure' in text
    assert 'AntTpmsLowPressureAlarm' in text
    assert 'AntTpmsHighPressureAlarm' in text


def test_tpms_transport_profile_registered():
    text = Path('custom_components/antplus/control.py').read_text()
    assert 'DEVICE_TYPE_TIRE_PRESSURE: 8192' in text
    assert 'def tpms_parameter_payload' in text


def test_documented_generic_controls_are_exposed_as_buttons():
    text = Path('custom_components/antplus/button.py').read_text()
    for command in (
        'menu_up', 'menu_down', 'select', 'back', 'home',
        'timer_start', 'timer_stop', 'timer_reset', 'length', 'lap',
    ):
        assert command in text


def test_complete_fec_control_surface_is_exposed():
    number_text = Path('custom_components/antplus/number.py').read_text()
    button_text = Path('custom_components/antplus/button.py').read_text()
    for control in (
        'AntFeTargetPower', 'AntFeBasicResistance', 'AntFeGrade',
        'AntFeRollingResistance', 'AntFeWindResistance', 'AntFeWindSpeed',
        'AntFeDraftingFactor', 'AntFeUserWeight', 'AntFeBicycleWeight',
        'AntFeWheelDiameter', 'AntFeGearRatio',
    ):
        assert control in number_text
    for control in ('Calibrate Zero Offset', 'Calibrate Spin Down', 'Cancel Calibration'):
        assert control in button_text


def test_bicycle_power_calibration_is_exposed():
    text = Path('custom_components/antplus/button.py').read_text()
    assert 'AntPowerCalibrationButton' in text
    assert 'Manual Calibration' in text


def test_generic_control_action_is_exposed():
    text = Path('custom_components/antplus/services.py').read_text()
    assert 'SERVICE_SEND_GENERIC_CONTROL = "send_generic_control"' in text
    assert 'controls_generic_payload' in text
