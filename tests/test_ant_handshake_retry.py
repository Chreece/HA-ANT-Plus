"""Static regression tests for gateway capture startup."""

from pathlib import Path


def test_gateway_retries_ant_handshake():
    source = Path("gateway/antplus_gateway.py").read_text()

    assert "CAPTURE_START_ATTEMPTS = 3" in source
    assert "CAPTURE_RETRY_DELAY = 2.0" in source
    assert "self._refresh_runtime_adapter()" in source
    assert "node.set_network_key(" in source
    assert "retrying in %.1fs" in source


def test_gateway_does_not_fake_running_after_failed_worker():
    source = Path("gateway/antplus_gateway.py").read_text()

    assert "def running(self) -> bool:" in source
    assert "if not scanner.running:" in source
    assert "self._enabled = False" in source
