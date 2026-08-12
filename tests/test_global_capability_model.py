from custom_components.antplus.capabilities import (
    CONTROL_DROPPER,
    CONTROL_FE_BASIC_RESISTANCE,
    CONTROL_FE_REQUEST_CAPABILITIES,
    CONTROL_FE_SIMULATION,
    CONTROL_FE_TARGET_POWER,
    CONTROL_FE_USER_CONFIGURATION,
    CONTROL_GENERIC,
    CONTROL_LEV,
    CONTROL_POWER_CALIBRATION,
    CONTROL_TPMS_CONFIGURATION,
    EVENT_DROPPER,
    EVENT_FE_COMMAND_STATUS,
    EVENT_GENERIC_CONTROL,
    EVENT_POWER_CALIBRATION,
    EVENT_SHIFT,
    capability_attributes,
    capability_signature,
    record_fe_command_status,
    record_observed_page,
    supports_control,
    supports_event,
)
from custom_components.antplus.const import (
    DEVICE_TYPE_CONTROLS,
    DEVICE_TYPE_DROPPER,
    DEVICE_TYPE_FITNESS_EQUIPMENT,
    DEVICE_TYPE_LEV,
    DEVICE_TYPE_POWER,
    DEVICE_TYPE_RUNNING_DYNAMICS,
    DEVICE_TYPE_SHIFTING,
    DEVICE_TYPE_STRIDE_SPEED,
    DEVICE_TYPE_TIRE_PRESSURE,
)
from custom_components.antplus.models import AntDevice


def device(*profiles: int) -> AntDevice:
    item = AntDevice(device_id=42)
    item.profiles.update(profiles)
    return item


def test_generic_controls_and_events_are_profile_capabilities():
    item = device(DEVICE_TYPE_CONTROLS)
    assert supports_control(item, CONTROL_GENERIC)
    assert supports_event(item, EVENT_GENERIC_CONTROL)


def test_fe_modes_are_hidden_until_explicit_capability_page():
    item = device(DEVICE_TYPE_FITNESS_EQUIPMENT)
    assert supports_control(item, CONTROL_FE_REQUEST_CAPABILITIES)
    assert not supports_control(item, CONTROL_FE_BASIC_RESISTANCE)
    assert not supports_control(item, CONTROL_FE_TARGET_POWER)
    assert not supports_control(item, CONTROL_FE_SIMULATION)
    assert supports_event(item, EVENT_FE_COMMAND_STATUS)

    # Page 54: basic + simulation supported, target power unsupported.
    record_observed_page(item, DEVICE_TYPE_FITNESS_EQUIPMENT, bytes.fromhex("36ffffffffffff05"))
    item.decoder_state["fe_capabilities"] = {
        "basic_resistance": True,
        "target_power": False,
        "simulation": True,
    }
    assert supports_control(item, CONTROL_FE_BASIC_RESISTANCE)
    assert not supports_control(item, CONTROL_FE_TARGET_POWER)
    assert supports_control(item, CONTROL_FE_SIMULATION)


def test_fe_user_configuration_requires_positive_page_evidence():
    item = device(DEVICE_TYPE_FITNESS_EQUIPMENT)
    item.decoder_state["fe_capabilities"] = {
        "basic_resistance": False,
        "target_power": False,
        "simulation": True,
    }
    assert not supports_control(item, CONTROL_FE_USER_CONFIGURATION)
    assert record_observed_page(item, DEVICE_TYPE_FITNESS_EQUIPMENT, bytes.fromhex("37ffffffffffffff"))
    assert supports_control(item, CONTROL_FE_USER_CONFIGURATION)


def test_fe_command_status_can_confirm_and_revoke_capability():
    item = device(DEVICE_TYPE_FITNESS_EQUIPMENT)
    assert not supports_control(item, CONTROL_FE_TARGET_POWER)
    assert record_fe_command_status(item, 0x31, 0)
    assert supports_control(item, CONTROL_FE_TARGET_POWER)
    assert record_fe_command_status(item, 0x31, 2)
    assert not supports_control(item, CONTROL_FE_TARGET_POWER)


def test_running_power_role_never_inherits_cycling_calibration_or_event():
    item = device(DEVICE_TYPE_POWER, DEVICE_TYPE_RUNNING_DYNAMICS, DEVICE_TYPE_STRIDE_SPEED)
    assert not supports_control(item, CONTROL_POWER_CALIBRATION)
    assert not supports_event(item, EVENT_POWER_CALIBRATION)


def test_cycling_power_role_keeps_calibration_and_event():
    item = device(DEVICE_TYPE_POWER)
    assert supports_control(item, CONTROL_POWER_CALIBRATION)
    assert supports_event(item, EVENT_POWER_CALIBRATION)


def test_other_implemented_controls_and_events_use_same_model():
    item = device(DEVICE_TYPE_LEV, DEVICE_TYPE_DROPPER, DEVICE_TYPE_TIRE_PRESSURE, DEVICE_TYPE_SHIFTING)
    assert supports_control(item, CONTROL_LEV)
    assert supports_control(item, CONTROL_DROPPER)
    assert supports_control(item, CONTROL_TPMS_CONFIGURATION)
    assert supports_event(item, EVENT_DROPPER)
    assert supports_event(item, EVENT_SHIFT)


def test_capability_signature_changes_with_positive_evidence():
    item = device(DEVICE_TYPE_FITNESS_EQUIPMENT)
    before = capability_signature(item)
    item.decoder_state["fe_capabilities"] = {
        "basic_resistance": True,
        "target_power": False,
        "simulation": False,
    }
    after = capability_signature(item)
    assert before != after
    attrs = capability_attributes(item)
    assert CONTROL_FE_BASIC_RESISTANCE in attrs["controls"]
    assert "evidence" in attrs
