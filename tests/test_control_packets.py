from custom_components.antplus.control import (
    bicycle_power_manual_calibration_payload,
    controls_generic_payload,
    fe_basic_resistance_payload,
    fe_calibration_payload,
    fe_target_power_payload,
    fe_track_resistance_payload,
    fe_user_configuration_payload,
    fe_wind_resistance_payload,
    request_data_page_payload,
    tpms_parameter_payload,
)

def test_fe_target_power_packet():
    assert fe_target_power_payload(250) == bytes.fromhex("31ffffffffff e803".replace(" ", ""))

def test_fe_basic_resistance_packet():
    assert fe_basic_resistance_payload(50) == bytes.fromhex("30ffffffffffff64")

def test_common_request_page_packet():
    assert request_data_page_payload(80, 1) == bytes.fromhex("46ffffffff015001")

def test_tpms_position_packet():
    assert tpms_parameter_payload(position=1, set_position=True)[0:2] == bytes((0x10, 0x11))


def test_generic_timer_start_packet():
    assert controls_generic_payload("timer_start", sequence=7) == bytes.fromhex("49ffffffff072000")


def test_fe_wind_simulation_packet():
    assert fe_wind_resistance_payload(
        wind_resistance_coefficient=0.51,
        wind_speed_kmh=0,
        drafting_factor=1.0,
    ) == bytes.fromhex("32ffffffff337f64")


def test_fe_track_simulation_packet():
    assert fe_track_resistance_payload(
        grade_percent=5.0,
        rolling_resistance_coefficient=0.004,
    ) == bytes.fromhex("33ffffffff145050")


def test_fe_user_configuration_packet():
    assert fe_user_configuration_payload(
        user_weight_kg=70.0,
        bicycle_weight_kg=10.0,
        wheel_diameter_m=0.700,
        gear_ratio=2.10,
    ) == bytes.fromhex("37581bff080c4646")


def test_fe_calibration_packets():
    assert fe_calibration_payload(zero_offset=True) == bytes.fromhex("014000ffffffffff")
    assert fe_calibration_payload(spin_down=True) == bytes.fromhex("018000ffffffffff")
    assert fe_calibration_payload(zero_offset=True, spin_down=True) == bytes.fromhex("01c000ffffffffff")
    assert fe_calibration_payload() == bytes.fromhex("010000ffffffffff")


def test_power_manual_calibration_packet():
    assert bicycle_power_manual_calibration_payload() == bytes.fromhex("01aaffffffffffff")
