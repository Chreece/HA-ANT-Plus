from custom_components.antplus.config_flow import UNIQUE_ID


def test_config_flow_unique_id_is_stable():
    assert UNIQUE_ID == "antplus_hub"
