from pathlib import Path

from custom_components.antplus.adapter import AntUsbAdapter


def test_subentry_name_uses_product_and_serial_only():
    adapter = AntUsbAdapter(
        vid="0fcf",
        pid="1008",
        serial="123",
        manufacturer="Dynastream Innovations",
        product="ANT USBStick2",
        source="remote",
        gateway_id="Gastezimmer",
        path="/dev/bus/usb/001/005",
    )

    assert adapter.subentry_name == "ANT USBStick2 123"
    assert "Gastezimmer" not in adapter.subentry_name
    assert "remote" not in adapter.subentry_name
    assert "/dev/" not in adapter.subentry_name


def test_subentry_name_without_serial_uses_usb_vid_pid_fallback():
    adapter = AntUsbAdapter(
        vid="0fcf",
        pid="1009",
        serial=None,
        product="ANTUSB-m",
        source="local",
        path="/sys/bus/usb/devices/1-2",
    )

    assert adapter.subentry_name == "ANTUSB-m 0FCF:1009"
    assert "local" not in adapter.subentry_name
    assert "/sys/" not in adapter.subentry_name


def test_adapter_subentry_callers_use_usb_only_name():
    # Every runtime caller that creates/updates a physical-adapter subentry
    # must use the host-independent USB-derived name.
    for filename in ("adapter_sensor.py", "switch.py"):
        source = (
            Path("custom_components/antplus") / filename
        ).read_text()

        assert "ensure_adapter_subentry" in source
        assert "record.adapter.subentry_name" in source

    # The helper itself stays generic and must not derive names from host,
    # gateway, transport or filesystem information.
    source = Path(
        "custom_components/antplus/subentries.py"
    ).read_text()

    assert "def ensure_adapter_subentry" in source
    assert "gateway_id" not in source
    assert "record.adapter.name" not in source
    assert "record.adapter.subentry_name" not in source


def test_subentry_name_does_not_reference_transport_fields():
    source = Path("custom_components/antplus/adapter.py").read_text()
    start = source.index("    def subentry_name(self)")
    end = source.index("\n    def identity_storage", start)
    body = source[start:end]

    assert "gateway_id" not in body
    assert "source" not in body
    assert "path" not in body
