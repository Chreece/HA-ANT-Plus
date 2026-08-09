from pathlib import Path


def test_adapter_entities_use_config_subentry_id():
    for name in ("adapter_sensor.py", "switch.py"):
        source = (Path("custom_components/antplus") / name).read_text()
        assert "config_subentry_id=subentry_id" in source


def test_sensor_entities_use_sensor_config_subentry():
    source = Path("custom_components/antplus/sensor.py").read_text()
    assert "config_subentry_id=sensors_subentry_id" in source


def test_cleanup_button_uses_sensor_config_subentry():
    source = Path("custom_components/antplus/button.py").read_text()
    assert "config_subentry_id=sensors_subentry_id" in source


def test_obsolete_synthetic_sensors_device_is_removed():
    source = Path("custom_components/antplus/__init__.py").read_text()
    assert "obsolete_sensors_parent" in source
    assert '(DOMAIN, "sensors")' in source
    assert "device_registry.async_remove_device(obsolete_sensors_parent.id)" in source
