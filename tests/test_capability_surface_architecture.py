from pathlib import Path


def test_all_control_platforms_use_central_capability_model():
    for filename in ("button.py", "number.py", "select.py", "switch.py"):
        text = Path("custom_components/antplus", filename).read_text(encoding="utf-8")
        assert "supports_control" in text, filename


def test_semantic_events_use_central_capability_model():
    text = Path("custom_components/antplus/events.py").read_text(encoding="utf-8")
    assert "supports_event" in text
    for event in (
        "EVENT_GENERIC_CONTROL",
        "EVENT_FE_CALIBRATION",
        "EVENT_POWER_CALIBRATION",
        "EVENT_SHIFT",
        "EVENT_DROPPER",
    ):
        assert event in text


def test_receiver_notifies_platforms_when_capabilities_change():
    text = Path("custom_components/antplus/receiver.py").read_text(encoding="utf-8")
    assert "capability_signature(device)" in text
    assert "or capability_changed" in text
    assert "record_fe_command_status" in text


def test_fe_capability_probe_is_automatic():
    text = Path("custom_components/antplus/button.py").read_text(encoding="utf-8")
    assert "request_data_page_payload(0x36)" in text
    assert "request_data_page_payload(0x37)" in text
