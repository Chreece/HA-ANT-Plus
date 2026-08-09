"""Tests for bus/address USB selection metadata."""

from custom_components.antplus.adapter import AntUsbAdapter


def test_bus_address_does_not_change_physical_identity():
    first = AntUsbAdapter(
        vid="0FCF",
        pid="1008",
        serial="123",
        bus=1,
        address=4,
    )
    second = AntUsbAdapter(
        vid="0FCF",
        pid="1008",
        serial="123",
        bus=2,
        address=9,
    )

    assert first.stable_key == "0FCF:1008:123"
    assert first.stable_key == second.stable_key
    assert first.ha_identifier == second.ha_identifier


def test_bus_address_from_mapping():
    adapter = AntUsbAdapter.from_mapping(
        {
            "vid": "0FCF",
            "pid": "1008",
            "serial": "123",
            "bus": 1,
            "address": 7,
        }
    )
    assert adapter.bus == 1
    assert adapter.address == 7
