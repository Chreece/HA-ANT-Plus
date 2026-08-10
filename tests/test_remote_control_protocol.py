from pathlib import Path

def test_gateway_advertises_confirmed_control_protocol():
    source = Path("gateway/antplus_gateway.py").read_text()
    assert 'CONTROL_PROTOCOL = 1' in source
    assert 'CONTROL_RESULT_EVENT = "antplus_adapter_control_result"' in source
    assert '"control_protocol": CONTROL_PROTOCOL' in source

def test_ha_waits_for_correlated_remote_control_result():
    source = Path("custom_components/antplus/adapter.py").read_text()
    assert 'command_id = uuid.uuid4().hex' in source
    assert 'await asyncio.wait_for(future, timeout=REMOTE_CONTROL_TIMEOUT)' in source
    assert 'resolve_remote_control_result' in source

def test_remote_listener_consumes_control_results():
    source = Path("custom_components/antplus/remote.py").read_text()
    assert 'REMOTE_ADAPTER_CONTROL_RESULT_EVENT' in source
    assert 'adapter_manager.resolve_remote_control_result(data)' in source
