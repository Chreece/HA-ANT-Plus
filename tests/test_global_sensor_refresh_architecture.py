from pathlib import Path


def test_ant_sensors_use_one_global_state_callback_and_timer():
    source = Path("custom_components/antplus/sensor.py").read_text()
    entity_start = source.index("class AntPlusSensor")
    entity_body = source[entity_start:]

    assert source.count("receiver.add_state_callback(") == 1
    assert source.count("async_track_time_interval(") == 1
    assert "receiver.add_state_callback(receiver_state_changed)" in source
    assert "refresh_availability_states" in source

    # Individual metric entities must not own receiver callbacks or timers.
    assert "add_state_callback" not in entity_body
    assert "async_track_time_interval" not in entity_body


def test_global_inactivity_refresh_writes_only_availability_transitions():
    source = Path("custom_components/antplus/sensor.py").read_text()
    start = source.index("def refresh_availability_states")
    end = source.index("def receiver_state_changed", start)
    body = source[start:end]

    assert "availability_cache" in body
    assert "previous == available" in body
    assert "global_sensor_refresh_writes" in body
