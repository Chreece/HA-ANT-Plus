"""Remote ANT+ gateway transport for HA ANT+."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .adapter import AntAdapterManager, AntUsbAdapter
from .const import (
    REMOTE_ADAPTER_CAPTURE_STATE_EVENT,
    REMOTE_ADAPTER_CONTROL_RESULT_EVENT,
    REMOTE_GATEWAY_HELLO_EVENT,
    REMOTE_GATEWAY_STATUS_EVENT,
    REMOTE_PACKET_EVENT,
)
from .receiver import AntPlusReceiver

_LOGGER = logging.getLogger(__name__)

REMOTE_PACKET_QUEUE_MAX = 4096
REMOTE_QUEUE_WARNING_INTERVAL = 250


def _payload_bytes(value: Any) -> bytes:
    if isinstance(value, str):
        cleaned = value.replace(" ", "").replace(":", "").replace("-", "")
        if len(cleaned) != 16:
            raise ValueError("payload hex string must contain exactly 8 bytes")
        return bytes.fromhex(cleaned)

    if isinstance(value, (list, tuple)):
        if len(value) != 8:
            raise ValueError("payload list must contain exactly 8 bytes")
        values = [int(item) for item in value]
        if any(item < 0 or item > 255 for item in values):
            raise ValueError("payload byte outside range 0..255")
        return bytes(values)

    raise ValueError("payload must be a hex string or list of 8 integers")


def _integer(packet: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = int(packet[key])
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} outside range {minimum}..{maximum}: {value}")
    return value


def _process_remote_packet(
    receiver: AntPlusReceiver,
    packet: dict[str, Any],
    gateway_id: str,
) -> None:
    adapter_id = str(packet.get("adapter_id", "")).strip()
    source = f"remote:{gateway_id}"
    if adapter_id:
        source += f":{adapter_id}"

    receiver.process_packet(
        device_id=_integer(packet, "device_id", 0, 0xFFFF),
        device_type=_integer(packet, "device_type", 0, 0xFF),
        transmission_type=_integer(packet, "transmission_type", 0, 0xFF),
        payload=_payload_bytes(packet.get("payload")),
        source=source,
    )



class RemotePacketWorker:
    """Decode remote ANT+ packets outside Home Assistant's event loop."""

    def __init__(self, receiver: AntPlusReceiver) -> None:
        self._receiver = receiver
        self._queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue(
            maxsize=REMOTE_PACKET_QUEUE_MAX
        )
        self._stop = threading.Event()
        self._dropped = 0
        self._thread = threading.Thread(
            target=self._run,
            name="antplus-remote-packet-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def dropped_packets(self) -> int:
        return self._dropped

    def enqueue(self, gateway_id: str, packet: dict[str, Any]) -> None:
        """Queue a packet without ever blocking HA's MainThread.

        If saturated, discard the oldest packet so current live telemetry wins
        over stale backlog. ANT+ broadcasts repeat rapidly, making this safer
        than allowing an unbounded queue to stall Home Assistant.
        """
        item = (gateway_id, dict(packet))
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass

        try:
            self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:
            pass

        self._dropped += 1
        if self._dropped == 1 or self._dropped % REMOTE_QUEUE_WARNING_INTERVAL == 0:
            _LOGGER.warning(
                "Remote ANT+ packet queue saturated; dropped %d stale packet(s)",
                self._dropped,
            )

        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # A producer raced us after the discard. Dropping this packet is
            # still preferable to blocking Home Assistant's event loop.
            self._dropped += 1

    def stop(self) -> None:
        """Stop the worker without blocking HA shutdown indefinitely."""
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self._queue.put_nowait(None)
            except queue.Empty:
                pass
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                if item is None:
                    return
                gateway_id, packet = item
                try:
                    _process_remote_packet(self._receiver, packet, gateway_id)
                except (KeyError, TypeError, ValueError) as err:
                    _LOGGER.warning(
                        "Ignoring invalid ANT+ packet from gateway %s: %s",
                        gateway_id,
                        err,
                    )
                except Exception:
                    _LOGGER.exception(
                        "Unexpected error decoding ANT+ packet from gateway %s",
                        gateway_id,
                    )
            finally:
                self._queue.task_done()

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
    """Register remote packets and gateway adapter-presence events."""

    packet_worker = RemotePacketWorker(receiver)

    @callback
    def handle_packet_event(event: Event) -> None:
        data = event.data
        gateway_id = str(data.get("gateway_id", "unknown")).strip() or "unknown"
        packets = data.get("packets")

        if packets is None:
            packets = [data]
        elif not isinstance(packets, list):
            return

        # Never decode ANT packets in Home Assistant's event loop. The remote
        # gateway can deliver hundreds of packets per second from multi-profile
        # devices such as Stryd; enqueue only and let the dedicated worker do
        # validation, OpenANT parsing and receiver updates.
        for packet in packets:
            if isinstance(packet, dict):
                packet_worker.enqueue(gateway_id, packet)

    @callback
    def handle_gateway_hello(event: Event) -> None:
        data = event.data
        gateway_id = str(data.get("gateway_id", "")).strip() or "unknown"
        adapters = _parse_adapters(data.get("adapters", []), gateway_id)

        if not adapters and isinstance(data.get("adapter"), dict):
            adapters = _parse_adapters([data["adapter"]], gateway_id)

        adapter_manager.update_remote_gateway(
            gateway_id,
            adapters,
            reconcile_capture=True,
            control_protocol=int(data.get("control_protocol", 0) or 0),
        )
        _LOGGER.info(
            "Remote ANT+ gateway connected: %s (%d adapter(s))",
            gateway_id,
            len(adapters),
        )

    @callback
    def handle_gateway_status(event: Event) -> None:
        data = event.data
        gateway_id = str(data.get("gateway_id", "")).strip() or "unknown"
        adapters = _parse_adapters(data.get("adapters", []), gateway_id)
        adapter_manager.update_remote_gateway(
            gateway_id,
            adapters,
            control_protocol=int(data.get("control_protocol", 0) or 0),
        )

    @callback
    def handle_control_result(event: Event) -> None:
        data = event.data
        gateway_id = str(data.get("gateway_id", "")).strip()
        if not gateway_id:
            return
        adapter_manager.resolve_remote_control_result(data)

    @callback
    def handle_capture_state(event: Event) -> None:
        data = event.data
        gateway_id = str(data.get("gateway_id", "")).strip()
        stable_key = str(data.get("adapter_id", "")).strip()
        if not gateway_id or not stable_key:
            return
        adapter_manager.update_remote_capture_state(
            gateway_id,
            stable_key,
            bool(data.get("enabled", False)),
            str(data.get("error")).strip() if data.get("error") else None,
        )

    unsub_packet = hass.bus.async_listen(
        REMOTE_PACKET_EVENT,
        handle_packet_event,
    )
    unsub_hello = hass.bus.async_listen(
        REMOTE_GATEWAY_HELLO_EVENT,
        handle_gateway_hello,
    )
    unsub_status = hass.bus.async_listen(
        REMOTE_GATEWAY_STATUS_EVENT,
        handle_gateway_status,
    )
    unsub_capture_state = hass.bus.async_listen(
        REMOTE_ADAPTER_CAPTURE_STATE_EVENT,
        handle_capture_state,
    )
    unsub_control_result = hass.bus.async_listen(
        REMOTE_ADAPTER_CONTROL_RESULT_EVENT,
        handle_control_result,
    )

    def unsubscribe() -> None:
        unsub_packet()
        packet_worker.stop()
        unsub_hello()
        unsub_status()
        unsub_capture_state()
        unsub_control_result()

    return unsubscribe
