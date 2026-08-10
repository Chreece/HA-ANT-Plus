from pathlib import Path
import re


def test_raw_diagnostics_are_bounded_per_profile():
    source = Path("custom_components/antplus/decoder.py").read_text()
    assert 'f"profile_{device_type}_raw"' in source
    assert 'f"profile_{device_type}_page_{page}_raw"' not in source


def test_old_page_specific_raw_entities_are_cleaned():
    source = Path("custom_components/antplus/__init__.py").read_text()
    assert r'_profile_\d+_page_\d+_raw$' in source


def test_discovery_and_metric_memory_are_bounded():
    source = Path("custom_components/antplus/receiver.py").read_text()
    assert "MAX_DISCOVERY_CANDIDATES = 256" in source
    assert "MAX_CONFIRMED_DEVICES = 256" in source
    assert "MAX_PROFILES_PER_DEVICE = 16" in source
    assert "MAX_METRICS_PER_DEVICE = 96" in source


def test_timestamp_only_metric_updates_do_not_notify_ha():
    source = Path("custom_components/antplus/receiver.py").read_text()
    assert "old.value != metric.value" in source
    assert "old != metric" not in source


def test_entity_creation_is_bounded():
    source = Path("custom_components/antplus/sensor.py").read_text()
    assert "MAX_ENTITIES_PER_ANT_DEVICE = 96" in source
    assert "device_entity_count >= MAX_ENTITIES_PER_ANT_DEVICE" in source


def test_per_entity_refresh_is_not_one_hz():
    source = Path("custom_components/antplus/sensor.py").read_text()
    assert "timedelta(seconds=1)" not in source
    assert "timedelta(seconds=5)" in source


def test_gateway_uses_bounded_coalescing():
    source = Path("gateway/antplus_gateway.py").read_text()
    assert "MAX_REMOTE_BATCH_PACKETS = 256" in source
    assert "MAX_REMOTE_DRAIN_PACKETS = 2048" in source
    assert "def _coalesce_packets(" in source
    assert "packets = _coalesce_packets(packets)" in source


def test_gateway_default_batch_interval_is_half_second():
    source = Path("gateway/antplus_gateway.py").read_text()
    assert 'os.environ.get("BATCH_INTERVAL", "0.5")' in source


def test_gateway_queue_is_bounded():
    source = Path("gateway/antplus_gateway.py").read_text()
    sizes = [int(x) for x in re.findall(r"maxsize=(\d+)", source)]
    assert sizes
    assert max(sizes) <= 2048
