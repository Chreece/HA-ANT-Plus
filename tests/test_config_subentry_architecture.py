from pathlib import Path


def test_no_fake_sensor_parent_device():
    entity = Path("custom_components/antplus/entity.py").read_text()
    button = Path("custom_components/antplus/button.py").read_text()
    const = Path("custom_components/antplus/const.py").read_text()
    assert "SENSORS_PARENT_IDENTIFIER" not in entity
    assert "SENSORS_PARENT_IDENTIFIER" not in button
    assert "SENSORS_PARENT_IDENTIFIER" not in const
    assert "via_device" not in entity


def test_sensor_entities_use_sensor_subentry():
    source = Path("custom_components/antplus/sensor.py").read_text()
    assert "sensors_subentry_id = ensure_sensor_subentry(hass, entry)" in source
    assert "subentry_id=sensors_subentry_id" in source


def test_adapter_entities_use_per_adapter_subentries():
    for name in ("adapter_sensor.py", "switch.py"):
        source = Path("custom_components/antplus") / name
        text = source.read_text()
        assert "ensure_adapter_subentry" in text
        assert "subentry_id=subentry_id" in text


def test_cleanup_belongs_to_sensor_subentry_without_device():
    source = Path("custom_components/antplus/button.py").read_text()
    assert "subentry_id=sensors_subentry_id" in source
    assert "def device_info" not in source


def test_distinct_sensor_device_identity_is_preserved():
    source = Path("custom_components/antplus/entity.py").read_text()
    assert '"identifiers": {(DOMAIN, str(dev.device_id))}' in source


def test_existing_devices_are_migrated_to_subentries():
    source = Path("custom_components/antplus/subentries.py").read_text()
    assert "new_config_subentry_id=sensors_sid" in source
    assert "new_config_subentry_id=sid" in source
    assert 'return f"antplus_adapter:{stable_key}"' in source


def test_optional_openant_imports_have_no_expected_traceback():
    source = Path("custom_components/antplus/openant_bridge.py").read_text()
    assert "except (ModuleNotFoundError, AttributeError):" in source
    expected = source.split("except (ModuleNotFoundError, AttributeError):", 1)[1]
    expected = expected.split("except Exception:", 1)[0]
    assert "exc_info=True" not in expected
