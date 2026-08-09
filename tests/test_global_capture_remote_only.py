"""Tests for remote-only/global Capture behavior."""

from custom_components.antplus.receiver import AntPlusReceiver


def test_capture_state_is_independent_from_local_receiver_state(monkeypatch):
    receiver = AntPlusReceiver()
    monkeypatch.setattr(receiver, "_local_usb_present", lambda: False)

    receiver.enable_capture()

    assert receiver.capture_enabled is True
    assert receiver.state == "remote"
    assert receiver.error is None

    receiver.disable_capture()
    assert receiver.capture_enabled is False
