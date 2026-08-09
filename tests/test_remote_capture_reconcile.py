from pathlib import Path


def test_gateway_hello_reconciles_persisted_capture_state():
    source = Path("custom_components/antplus/remote.py").read_text()

    assert "reconcile_capture=True" in source


def test_gateway_status_does_not_force_capture_reconciliation():
    source = Path("custom_components/antplus/remote.py").read_text()

    start = source.index("def handle_gateway_status")
    end = source.index("def handle_capture_state", start)
    body = source[start:end]

    assert "update_remote_gateway(gateway_id, adapters)" in body
    assert "reconcile_capture=True" not in body


def test_manager_replays_capture_on_new_gateway_session():
    source = Path("custom_components/antplus/adapter.py").read_text()

    assert "reconcile_capture: bool = False" in source
    assert "if new_presence or reconcile_capture:" in source
