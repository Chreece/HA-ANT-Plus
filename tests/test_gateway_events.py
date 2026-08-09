"""Gateway event-name tests."""
from custom_components.antplus.const import (
    REMOTE_CAPTURE_STATE_EVENT,
    REMOTE_GATEWAY_HELLO_EVENT,
    REMOTE_PACKET_EVENT,
)

def test_gateway_event_names():
    assert REMOTE_PACKET_EVENT == "antplus_remote_packet"
    assert REMOTE_GATEWAY_HELLO_EVENT == "antplus_gateway_hello"
    assert REMOTE_CAPTURE_STATE_EVENT == "antplus_capture_state"
