"""Tests for optimistic Capture state followed by physical confirmation."""

from custom_components.antplus.adapter import AdapterPresence, AntUsbAdapter


def make_record() -> AdapterPresence:
    return AdapterPresence(
        adapter=AntUsbAdapter(
            vid="0FCF",
            pid="1008",
            serial="123",
        )
    )


def test_confirmed_off() -> None:
    record = make_record()

    assert record.capture_enabled is False
    assert record.displayed_capture is False


def test_pending_on_is_displayed_immediately() -> None:
    record = make_record()

    record.pending_capture = True

    assert record.capture_enabled is False
    assert record.displayed_capture is True


def test_pending_off_is_displayed_immediately() -> None:
    record = make_record()
    record.remote_capture_states["Gastezimmer"] = True

    assert record.capture_enabled is True

    record.pending_capture = False

    assert record.displayed_capture is False


def test_confirmed_state_used_after_pending_cleared() -> None:
    record = make_record()

    record.pending_capture = True
    assert record.displayed_capture is True

    record.pending_capture = None

    assert record.displayed_capture is False


def test_confirmed_remote_on() -> None:
    record = make_record()
    record.remote_capture_states["Gastezimmer"] = True

    assert record.capture_enabled is True
    assert record.displayed_capture is True
