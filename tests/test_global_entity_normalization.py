from pathlib import Path


def test_openant_global_normalization_rules_are_present():
    source = Path("custom_components/antplus/openant_bridge.py").read_text()

    # Exact aliases for fields that otherwise duplicate native semantic state.
    for mapping in (
        '"beat_count": "heart_beat_count"',
        '"beat_time": "heart_beat_time"',
        '"manufacturer_id_lsb": "manufacturer_id"',
        '"serial_number": "device_serial_fragment"',
        '"battery_percentage": "battery_level"',
        '"battery_soc": "battery_level"',
        '"status": "battery_status"',
        '"operating_time": "battery_operating_time"',
    ):
        assert mapping in source

    # Component-only values are represented by canonical composite metrics and
    # the bounded raw page diagnostic instead of standalone duplicate entities.
    for field in ("page_specific", "voltage_coarse", "voltage_fractional"):
        assert f'"{field}"' in source.split("suppressed_components = {", 1)[1].split("}", 1)[0]


def test_legacy_duplicate_entities_are_cleaned_globally():
    source = Path("custom_components/antplus/__init__.py").read_text()
    for suffix in (
        "_page_specific",
        "_voltage_coarse",
        "_voltage_fractional",
        "_manufacturer_id_lsb",
        "_beat_count",
        "_beat_time",
    ):
        assert f'"{suffix}"' in source
    assert 're.fullmatch(r"\\d+_status", unique_id)' in source


def test_common_battery_fields_have_unambiguous_names():
    source = Path("custom_components/antplus/decoder.py").read_text()
    for key in (
        '"battery_id"',
        '"battery_count"',
        '"battery_operating_time"',
        '"battery_voltage"',
        '"battery_status"',
    ):
        assert key in source


def test_profile_specific_battery_pages_are_not_common_battery_pages():
    source = Path("custom_components/antplus/openant_bridge.py").read_text()
    assert 'and "battery_id" in values' in source
    assert 'and "voltage_coarse" in values' in source
    assert 'and "voltage_fractional" in values' in source
