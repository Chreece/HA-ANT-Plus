"""Per-adapter capture identity tests."""

from custom_components.antplus.adapter import AntUsbAdapter


def test_capture_identity_is_physical_adapter_identity():
    local = AntUsbAdapter(
        vid="0FCF",
        pid="1008",
        serial="123",
        source="local",
    )
    remote = AntUsbAdapter(
        vid="0FCF",
        pid="1008",
        serial="123",
        source="remote",
        gateway_id="Gastezimmer",
    )

    assert local.stable_key == "0FCF:1008:123"
    assert local.stable_key == remote.stable_key
    assert local.ha_identifier == remote.ha_identifier


def test_different_usb_serial_gets_different_capture_device():
    first = AntUsbAdapter(vid="0FCF", pid="1008", serial="123")
    second = AntUsbAdapter(vid="0FCF", pid="1008", serial="456")

    assert first.stable_key != second.stable_key
