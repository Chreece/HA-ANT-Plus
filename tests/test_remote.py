"""Tests for remote ANT+ packet ingestion."""

from custom_components.antplus.receiver import AntPlusReceiver
from custom_components.antplus.remote import _payload_bytes


def test_remote_payload_hex():
    assert _payload_bytes(
        "00 01 02 03 04 05 06 07"
    ) == bytes(range(8))


def test_remote_payload_list():
    assert _payload_bytes(
        [0, 1, 2, 3, 4, 5, 6, 7]
    ) == bytes(range(8))


def test_same_ant_id_merges_sources():
    receiver = AntPlusReceiver()

    # Heart-rate-shaped packet.
    receiver.process_packet(
        device_id=12345,
        device_type=120,
        transmission_type=1,
        payload=bytes([0, 0, 0, 0, 0, 0, 0, 75]),
        source="remote:gym-pi",
    )

    # Same ANT ID seen through another source/profile.
    receiver.process_packet(
        device_id=12345,
        device_type=124,
        transmission_type=5,
        payload=bytes([0, 0, 0, 0, 0, 0, 0, 0]),
        source="local",
    )

    assert len(receiver.devices) == 1

    device = receiver.devices[12345]

    assert 120 in device.profiles
    assert 124 in device.profiles

    assert device.decoder_state["sources"] == {
        "remote:gym-pi",
        "local",
    }


def test_global_capture_blocks_remote_packets():
    receiver = AntPlusReceiver()

    receiver.disable_capture()

    receiver.process_packet(
        device_id=60000,
        device_type=120,
        transmission_type=1,
        payload=bytes([0, 0, 0, 0, 0, 0, 0, 80]),
        source="remote:test-gateway",
    )

    assert receiver.devices == {}


def test_global_capture_accepts_remote_after_enable():
    receiver = AntPlusReceiver()

    receiver.disable_capture()

    # Do not call enable_capture() here because it also attempts to start
    # physical USB hardware. Enable the state directly for this unit test.
    receiver._capture_enabled = True

    receiver.process_packet(
        device_id=60000,
        device_type=120,
        transmission_type=1,
        payload=bytes([0, 0, 0, 0, 0, 0, 0, 80]),
        source="remote:test-gateway",
    )

    assert 60000 in receiver.devices
