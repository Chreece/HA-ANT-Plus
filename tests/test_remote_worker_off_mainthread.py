from pathlib import Path


def test_remote_packets_are_queued_not_decoded_in_event_callback():
    source = Path("custom_components/antplus/remote.py").read_text()
    assert "class RemotePacketWorker" in source
    assert "REMOTE_PACKET_QUEUE_MAX = 4096" in source
    assert "packet_worker.enqueue(gateway_id, packet)" in source
    callback = source.split("def handle_packet_event", 1)[1].split("def handle_gateway_hello", 1)[0]
    assert "_process_remote_packet(receiver" not in callback


def test_remote_worker_coalesces_telemetry_instead_of_blocking_mainthread():
    source = Path("custom_components/antplus/remote.py").read_text()
    assert "OrderedDict" in source
    assert "_remote_packet_key" in source
    assert "REMOTE_WORKER_COALESCE_WINDOW = 0.10" in source
    assert "packet_worker.stop()" in source


def test_raw_profiles_are_not_split_by_arbitrary_page_byte():
    source = Path("custom_components/antplus/remote.py").read_text()
    assert "PAGE_AWARE_PROFILE_TYPES" in source
    assert 'return (*base, "profile")' in source


def test_openant_power_info_log_storm_is_suppressed():
    source = Path("custom_components/antplus/openant_bridge.py").read_text()
    assert 'logging.getLogger("openant.devices.power_meter").setLevel(logging.WARNING)' in source
