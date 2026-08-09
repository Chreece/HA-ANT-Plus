from pathlib import Path


def test_receiver_has_candidate_threshold():
    source = Path("custom_components/antplus/receiver.py").read_text()
    assert "DISCOVERY_CONFIRM_PACKETS = 5" in source
    assert "DISCOVERY_CONFIRM_WINDOW_SECONDS = 10.0" in source
    assert "DISCOVERY_CANDIDATE_TTL_SECONDS = 30.0" in source


def test_new_device_or_profile_requires_confirmation():
    source = Path("custom_components/antplus/receiver.py").read_text()
    assert "needs_confirmation = (" in source
    assert "device is None" in source
    assert "device_type not in device.profiles" in source
    assert "and not self._candidate_confirmed(" in source


def test_confirmed_profiles_bypass_candidate_filter():
    source = Path("custom_components/antplus/receiver.py").read_text()
    assert "if needs_confirmation and not self._candidate_confirmed(" in source
