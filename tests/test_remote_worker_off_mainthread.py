from pathlib import Path


def test_remote_packets_are_queued_not_decoded_in_event_callback():
    source = Path("custom_components/antplus/remote.py").read_text()
    assert "class RemotePacketWorker" in source
    assert "REMOTE_PACKET_QUEUE_MAX = 4096" in source
    assert "packet_worker.enqueue(gateway_id, packet)" in source
    callback = source.split("def handle_packet_event", 1)[1].split("def handle_gateway_hello", 1)[0]
    assert "_process_remote_packet(receiver" not in callback


def test_remote_worker_drops_oldest_instead_of_blocking_mainthread():
    source = Path("custom_components/antplus/remote.py").read_text()
    assert "put_nowait" in source
    assert "get_nowait" in source
    assert "packet_worker.stop()" in source


def test_openant_power_info_log_storm_is_suppressed():
    source = Path("custom_components/antplus/openant_bridge.py").read_text()
    assert 'logging.getLogger("openant.devices.power_meter").setLevel(logging.WARNING)' in source
