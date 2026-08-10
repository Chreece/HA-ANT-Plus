from pathlib import Path


def test_gateway_coalesces_before_websocket_transport():
    source = Path("gateway/antplus_gateway.py").read_text()
    assert "TELEMETRY_PROTOCOL = 2" in source
    assert "class GatewayPacketBuffer" in source
    assert "_packet_is_event" in source
    assert "PAGE_AWARE_PROFILE_TYPES" in source
    assert 'return (*base, "profile")' in source


def test_event_profiles_bypass_telemetry_replacement():
    source = Path("gateway/antplus_gateway.py").read_text()
    assert "EVENT_PROFILE_TYPES = {16, 34, 115}" in source
    assert "device_type == 17 and page == 0x47" in source
    assert "return events + [latest[key] for key in order]" in source


def test_ha_metric_writes_are_globally_coalesced():
    source = Path("custom_components/antplus/sensor.py").read_text()
    assert "pending_metric_updates" in source
    assert "hass.loop.call_later(0.1, flush_metric_updates)" in source
    assert "one receiver callback per entity" in source
    # There should only be one registration in setup, not one in every sensor.
    assert source.count("receiver.add_metric_callback(metric_changed)") == 1
