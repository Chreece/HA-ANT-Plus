from custom_components.antplus.adapter import AdapterPresence, AntUsbAdapter


def test_desired_on_does_not_fake_actual_on():
    record = AdapterPresence(
        adapter=AntUsbAdapter(vid="0FCF", pid="1008", serial="123"),
        desired_capture=True,
    )
    assert record.capture_enabled is False


def test_remote_confirmation_drives_actual_switch_state():
    record = AdapterPresence(
        adapter=AntUsbAdapter(vid="0FCF", pid="1008", serial="123")
    )
    record.remote_capture_states["Gastezimmer"] = True
    assert record.capture_enabled is True
    record.remote_capture_states["Gastezimmer"] = False
    assert record.capture_enabled is False


def test_local_confirmation_drives_actual_switch_state():
    record = AdapterPresence(
        adapter=AntUsbAdapter(vid="0FCF", pid="1008", serial="123")
    )
    record.local_capture_enabled = True
    assert record.capture_enabled is True
