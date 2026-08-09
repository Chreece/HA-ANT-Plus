"""Remote ANT+ gateway transport for HA ANT+."""

from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .adapter import AntAdapterManager, AntUsbAdapter
from .const import (
    REMOTE_CAPTURE_STATE_EVENT,
    REMOTE_GATEWAY_HELLO_EVENT,
    REMOTE_GATEWAY_STATUS_EVENT,
    REMOTE_PACKET_EVENT,
)
from .receiver import AntPlusReceiver

_LOGGER = logging.getLogger(__name__)


def _payload_bytes(value: Any) -> bytes:
    if isinstance(value, str):
        cleaned = value.replace(" ", "").replace(":", "").replace("-", "")
        if len(cleaned) != 16:
            raise ValueError("payload hex string must contain exactly 8 bytes")
        try:
            return bytes.fromhex(cleaned)
        except ValueError as err:
            raise ValueError("payload is not valid hexadecimal") from err

    if isinstance(value, (list, tuple)):
        if len(value) != 8:
            raise ValueError("payload list must contain exactly 8 bytes")
        try:
            values = [int(item) for item in value]
        except (TypeError, ValueError) as err:
            raise ValueError("payload list contains a non-integer value") from err
        if any(item < 0 or item > 255 for item in values):
            raise ValueError("payload byte outside range 0..255")
        return bytes(values)

    raise ValueError("payload must be a hex string or list of 8 integers")


def _integer(packet: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    if key not in packet:
        raise ValueError(f"missing field: {key}")
    try:
        value = int(packet[key])
    except (TypeError, ValueError) as err:
        raise ValueError(f"{key} must be an integer") from err
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} outside range {minimum}..{maximum}: {value}")
    return value


def _process_remote_packet(
    receiver: AntPlusReceiver,
    packet: dict[str, Any],
    gateway_id: str,
) -> None:
    receiver.process_packet(
        device_id=_integer(packet, "device_id", 0, 0xFFFF),
        device_type=_integer(packet, "device_type", 0, 0xFF),
        transmission_type=_integer(packet, "transmission_type", 0, 0xFF),
        payload=_payload_bytes(packet.get("payload")),
        source=f"remote:{gateway_id}",
    )


def _parse_adapters(value: Any, gateway_id: str) -> list[AntUsbAdapter]:
    if not isinstance(value, list):
        return []

    result: list[AntUsbAdapter] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            result.append(
                AntUsbAdapter.from_mapping(
                    {
                        **item,
                        "source": "remote",
                        "gateway_id": gateway_id,
                    }
                )
            )
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning(
                "Ignoring invalid adapter metadata from gateway %s",
                gateway_id,
            )
    return result


def async_register_remote_listener(
    hass: HomeAssistant,
    entry: ConfigEntry,
    receiver: AntPlusReceiver,
    adapter_manager: AntAdapterManager,
) -> Callable[[], None]:
    """Register remote packets, gateway presence and capture-state sync."""

    def fire_capture_state(gateway_id: str | None = None) -> None:
        data: dict[str, Any] = {"enabled": receiver.capture_enabled}
        if gateway_id:
            data["gateway_id"] = gateway_id
        hass.bus.async_fire(REMOTE_CAPTURE_STATE_EVENT, data)

    @callback
    def handle_packet_event(event: Event) -> None:
        data = event.data
        gateway_id = str(data.get("gateway_id", "unknown")).strip() or "unknown"
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
                continue
            try:
                _process_remote_packet(receiver, packet, gateway_id)
            except (TypeError, ValueError) as err:
                _LOGGER.warning(
                    "Ignoring invalid ANT+ packet from gateway %s: %s",
                    gateway_id,
                    err,
                )

    @callback
    def handle_gateway_hello(event: Event) -> None:
        data = event.data
        gateway_id = str(data.get("gateway_id", "")).strip() or "unknown"

        adapters = _parse_adapters(data.get("adapters", []), gateway_id)

        if not adapters and isinstance(data.get("adapter"), dict):
            adapters = _parse_adapters([data["adapter"]], gateway_id)

        adapter_manager.update_remote_gateway(gateway_id, adapters)

        _LOGGER.info(
            "Remote ANT+ gateway connected: %s (%d adapter(s))",
            gateway_id,
            len(adapters),
        )
        fire_capture_state(gateway_id)

    @callback
    def handle_gateway_status(event: Event) -> None:
        data = event.data
        gateway_id = str(data.get("gateway_id", "")).strip() or "unknown"
        adapters = _parse_adapters(data.get("adapters", []), gateway_id)
        adapter_manager.update_remote_gateway(gateway_id, adapters)

    def receiver_changed() -> None:
        hass.loop.call_soon_threadsafe(fire_capture_state)

    unsub_packet = hass.bus.async_listen(REMOTE_PACKET_EVENT, handle_packet_event)
    unsub_hello = hass.bus.async_listen(REMOTE_GATEWAY_HELLO_EVENT, handle_gateway_hello)
    unsub_status = hass.bus.async_listen(REMOTE_GATEWAY_STATUS_EVENT, handle_gateway_status)
    unsub_receiver = receiver.add_state_callback(receiver_changed)

    def unsubscribe() -> None:
        unsub_packet()
        unsub_hello()
        unsub_status()
        unsub_receiver()

    return unsubscribe
