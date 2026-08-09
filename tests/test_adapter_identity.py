"""Tests for physical ANT USB adapter identity."""

from custom_components.antplus.adapter import AntUsbAdapter


def test_serial_number_defines_cross_host_identity():
    local = AntUsbAdapter(
        vid="0fcf",
        pid="1008",
        serial="123",
        manufacturer="Dynastream Innovations",
        product="ANT USBStick2",
        path="/sys/bus/usb/devices/1-4",
        source="local",
    )

    remote = AntUsbAdapter(
        vid="0FCF",
        pid="1008",
        serial="123",
        manufacturer="Dynastream Innovations",
        product="ANT USBStick2",
        path="/sys/bus/usb/devices/2-1",
        source="remote",
        gateway_id="jetson-nano",
    )

    assert local.stable_key == remote.stable_key
    assert local.ha_identifier == remote.ha_identifier


def test_different_serial_is_different_adapter():
    one = AntUsbAdapter(vid="0FCF", pid="1008", serial="123")
    two = AntUsbAdapter(vid="0FCF", pid="1008", serial="456")

    assert one.stable_key != two.stable_key
    assert one.ha_identifier != two.ha_identifier
