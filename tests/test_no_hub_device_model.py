"""No-hub device model tests."""

from custom_components.antplus.adapter import AntUsbAdapter


def test_physical_usb_identity_ignores_transport():
    local = AntUsbAdapter(
        vid="0FCF",
        pid="1008",
        serial="123",
        source="local",
        path="/sys/bus/usb/devices/1-4",
    )
    remote = AntUsbAdapter(
        vid="0FCF",
        pid="1008",
        serial="123",
        source="remote",
        gateway_id="Gastezimmer",
        path="/sys/bus/usb/devices/2-1",
    )

    assert local.stable_key == remote.stable_key
    assert local.ha_identifier == remote.ha_identifier
    assert local.ha_identifier == (
        "antplus",
        "usb_adapter:0FCF:1008:123",
    )
