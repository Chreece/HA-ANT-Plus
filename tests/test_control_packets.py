from custom_components.antplus.control import (
    fe_basic_resistance_payload,
    fe_target_power_payload,
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
