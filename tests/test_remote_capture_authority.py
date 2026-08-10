from pathlib import Path


def test_remote_rf_packet_confirms_capture_on():
    source = Path("custom_components/antplus/remote.py").read_text()
    start = source.index("def handle_packet_event")
    end = source.index("def handle_gateway_hello", start)
    body = source[start:end]
    assert "active_adapters" in body
    assert "update_remote_capture_state" in body
    assert "True" in body


def test_gateway_reports_authoritative_capture_states():
    gateway = Path("gateway/antplus_gateway.py").read_text()
    remote = Path("custom_components/antplus/remote.py").read_text()
    assert 'TELEMETRY_PROTOCOL = 2' in gateway
    assert '"capture_states": self.capture_states()' in gateway
    assert gateway.count('"capture_states": self.capture_states()') >= 2
    assert 'capture_states = data.get("capture_states")' in remote
    assert remote.count('capture_states = data.get("capture_states")') >= 2


def test_gateway_stop_reports_capture_off():
    gateway = Path("gateway/antplus_gateway.py").read_text()
    start = gateway.index("    def stop(self) -> None:", gateway.index("class AntScanner"))
    end = gateway.index("    def _refresh_runtime_adapter", start)
    body = gateway[start:end]
    assert "self._report_state(False)" in body
