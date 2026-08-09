"""Tests for confirmed-absence availability semantics."""

from custom_components.antplus.adapter import AdapterPresence, AntUsbAdapter


def test_remote_missing_state_is_separate_from_presence():
    record = AdapterPresence(
        adapter=AntUsbAdapter(vid="0FCF", pid="1008", serial="123")
    )
    record.remote_gateways["Gastezimmer"] = 1.0

    assert record.available
    assert record.remote_missing_since == {}


def test_local_presence_uses_missing_timer():
    record = AdapterPresence(
        adapter=AntUsbAdapter(vid="0FCF", pid="1008", serial="123"),
        local_present=True,
    )

    assert record.available
    assert record.local_missing_since is None
