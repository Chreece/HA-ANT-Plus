from custom_components.antplus.const import DEVICE_TYPE_NAMES
from custom_components.antplus.decoder_adapters import DECODER_ADAPTERS, NativeAntPlusAdapter, OpenAntAdapter
from custom_components.antplus.documented_profiles import DOCUMENTED_PROFILES, documented_profile_types
from custom_components.antplus.profile_support import PROFILE_SUPPORT, profile_support_rows


def test_exactly_two_decoder_backends():
    assert len(DECODER_ADAPTERS) == 2
    assert isinstance(DECODER_ADAPTERS[0], NativeAntPlusAdapter)
    assert isinstance(DECODER_ADAPTERS[1], OpenAntAdapter)


def test_native_adapter_recognizes_every_named_profile():
    adapter = NativeAntPlusAdapter()
    assert all(adapter.supports(device_type) for device_type in DEVICE_TYPE_NAMES)


def test_every_named_profile_has_documented_capability_row():
    assert set(DEVICE_TYPE_NAMES) <= documented_profile_types()
    assert set(DEVICE_TYPE_NAMES) <= set(PROFILE_SUPPORT)


def test_documented_rows_are_not_empty():
    for item in DOCUMENTED_PROFILES.values():
        assert item.name
        assert item.capabilities
        assert item.passive_role


def test_profile_matrix_exposes_both_backends():
    rows = profile_support_rows()
    assert rows
    for row in rows:
        assert row["native_adapter"] is True
        assert "openant_adapter" in row
        assert "documented_capabilities" in row


def test_extended_display_is_recognized():
    assert DEVICE_TYPE_NAMES[38] == "Extended Display"
    assert 38 in DOCUMENTED_PROFILES
