from pathlib import Path


def test_legacy_capture_state_is_migrated_before_records_are_created():
    source = Path("custom_components/antplus/adapter.py").read_text()

    migration = source.index(
        'and "capture_enabled" in data'
    )
    save = source.index(
        "await self._async_save_capture_states()",
        migration,
    )
    create_records = source.index(
        "for data in self._known_adapters().values():",
        save,
    )

    assert migration < save < create_records


def test_existing_new_store_state_wins_over_legacy_state():
    source = Path("custom_components/antplus/adapter.py").read_text()

    assert (
        "stable_key not in self._stored_capture_states"
        in source
    )
    assert (
        'self._stored_capture_states[stable_key] = bool('
        in source
    )
