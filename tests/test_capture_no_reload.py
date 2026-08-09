from pathlib import Path


def test_capture_toggle_does_not_persist_config_entry():
    source = Path("custom_components/antplus/adapter.py").read_text()

    start = source.index("    async def async_set_capture(")
    end = source.index("\n    async def async_refresh_local", start)
    body = source[start:end]

    assert "_persist_record(record)" not in body
    assert "record.desired_capture = bool(enabled)" in body


def test_persisted_adapter_data_excludes_capture_state():
    source = Path("custom_components/antplus/adapter.py").read_text()

    start = source.index("    def _persist_record(")
    end = source.index("\n    def _merge_or_register_device", start)
    body = source[start:end]

    assert 'stored["capture_enabled"]' not in body
    assert "identity_storage()" in body
