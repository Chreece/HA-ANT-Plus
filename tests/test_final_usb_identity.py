"""Final USB adapter identity tests."""

from custom_components.antplus.adapter import AntUsbAdapter


def test_usb_identity_does_not_depend_on_transport():
    local = AntUsbAdapter(
        vid="0fcf",
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

    assert local.stable_key == "0FCF:1008:123"
    assert local.stable_key == remote.stable_key
    assert local.ha_identifier == remote.ha_identifier
