"""Receive raw ANT+ packets forwarded through Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback

from .const import REMOTE_PACKET_EVENT
from .receiver import AntPlusReceiver

_LOGGER = logging.getLogger(__name__)


def _payload_bytes(value: Any) -> bytes:
    """Convert a remote packet payload to exactly eight bytes."""
    if isinstance(value, str):
        # Accept:
        # 0011223344556677
        # 00 11 22 33 44 55 66 77
        # 00:11:22:33:44:55:66:77
        cleaned = (
            value.replace(" ", "")
            .replace(":", "")
            .replace("-", "")
        )

        if len(cleaned) != 16:
            raise ValueError("payload hex string must contain exactly 8 bytes")

        try:
            payload = bytes.fromhex(cleaned)
        except ValueError as err:
            raise ValueError("payload is not valid hexadecimal") from err

    elif isinstance(value, (list, tuple)):
        if len(value) != 8:
            raise ValueError("payload list must contain exactly 8 bytes")

        try:
            values = [int(item) for item in value]
        except (TypeError, ValueError) as err:
            raise ValueError("payload list contains a non-integer value") from err

        if any(item < 0 or item > 255 for item in values):
            raise ValueError("payload byte outside range 0..255")

        payload = bytes(values)

    else:
        raise ValueError("payload must be a hex string or list of 8 integers")

    if len(payload) != 8:
        raise ValueError("payload must contain exactly 8 bytes")

    return payload


def _integer(packet: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    """Read and validate an integer field."""
    if key not in packet:
        raise ValueError(f"missing field: {key}")

    try:
        value = int(packet[key])
    except (TypeError, ValueError) as err:
        raise ValueError(f"{key} must be an integer") from err

    if not minimum <= value <= maximum:
        raise ValueError(
            f"{key} outside range {minimum}..{maximum}: {value}"
        )

    return value


def _process_remote_packet(
    receiver: AntPlusReceiver,
    packet: dict[str, Any],
    gateway_id: str,
) -> None:
    """Validate and process one forwarded packet."""
    device_id = _integer(packet, "device_id", 0, 0xFFFF)
    device_type = _integer(packet, "device_type", 0, 0xFF)
    transmission_type = _integer(packet, "transmission_type", 0, 0xFF)
    payload = _payload_bytes(packet.get("payload"))

    receiver.process_packet(
        device_id=device_id,
        device_type=device_type,
        transmission_type=transmission_type,
        payload=payload,
        source=f"remote:{gateway_id}",
    )


def async_register_remote_listener(
    hass: HomeAssistant,
    receiver: AntPlusReceiver,
):
    """Register the Home Assistant event listener for remote ANT+ packets."""

    @callback
    def handle_event(event: Event) -> None:
        data = event.data

        gateway_id_raw = data.get("gateway_id", "unknown")
        gateway_id = str(gateway_id_raw).strip() or "unknown"

        packets = data.get("packets")

        if packets is None:
            packets = [data]
        elif not isinstance(packets, list):
            _LOGGER.warning(
                "Ignoring remote ANT+ event from %s: packets must be a list",
                gateway_id,
            )
            return

        for packet in packets:
            if not isinstance(packet, dict):
                _LOGGER.warning(
                    "Ignoring malformed ANT+ packet from gateway %s",
                    gateway_id,
                )
                continue

            try:
                _process_remote_packet(receiver, packet, gateway_id)
            except (TypeError, ValueError) as err:
                _LOGGER.warning(
                    "Ignoring invalid ANT+ packet from gateway %s: %s",
                    gateway_id,
                    err,
                )

    return hass.bus.async_listen(
        REMOTE_PACKET_EVENT,
        handle_event,
    )
