"""Remote ANT+ gateway transport for HA ANT+."""

from __future__ import annotations

import logging
from collections import OrderedDict, deque
import threading
import time
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
REMOTE_EVENT_QUEUE_MAX = 1024
REMOTE_QUEUE_WARNING_INTERVAL = 250
REMOTE_WORKER_COALESCE_WINDOW = 0.10

PAGE_AWARE_PROFILE_TYPES = {
    11, 16, 17, 20, 25, 34, 48, 115, 120, 121, 122, 123, 124, 127
}
EVENT_PROFILE_TYPES = {16, 34, 115}


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



def _remote_packet_page(packet: dict[str, Any]) -> int:
    payload = packet.get("payload")
    if isinstance(payload, str):
        cleaned = payload.replace(" ", "").replace(":", "").replace("-", "")
        try:
            return int(cleaned[:2], 16) & 0x7F if len(cleaned) >= 2 else -1
        except ValueError:
            return -1
    if isinstance(payload, (list, tuple)) and payload:
        try:
            return int(payload[0]) & 0x7F
        except (TypeError, ValueError):
            return -1
    return -1


def _remote_packet_is_event(packet: dict[str, Any]) -> bool:
    try:
        device_type = int(packet.get("device_type", -1))
    except (TypeError, ValueError):
        return False
    page = _remote_packet_page(packet)
    if device_type in EVENT_PROFILE_TYPES:
        return True
    return device_type == 17 and page == 0x47


def _remote_packet_key(gateway_id: str, packet: dict[str, Any]) -> tuple:
    try:
        device_type = int(packet.get("device_type", -1))
    except (TypeError, ValueError):
        device_type = -1
    base = (
        gateway_id,
        packet.get("adapter_id"),
        packet.get("device_id"),
        device_type,
        packet.get("transmission_type"),
    )
    if device_type in PAGE_AWARE_PROFILE_TYPES:
        return (*base, _remote_packet_page(packet))
    return (*base, "profile")


class RemotePacketWorker:
    """Decode remote ANT+ telemetry outside HA and coalesce RF repetitions."""

    def __init__(self, receiver: AntPlusReceiver) -> None:
        self._receiver = receiver
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._telemetry: OrderedDict[tuple, tuple[str, dict[str, Any]]] = OrderedDict()
        self._events: deque[tuple[str, dict[str, Any]]] = deque(maxlen=REMOTE_EVENT_QUEUE_MAX)
        self._dropped = 0
        self._diagnostics = receiver.diagnostics
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
        """Store newest telemetry while preserving discrete event packets."""
        self._diagnostics.inc("remote_packets_received")
        item = (gateway_id, dict(packet))
        with self._lock:
            if _remote_packet_is_event(packet):
                self._diagnostics.inc("remote_event_packets")
                if len(self._events) >= REMOTE_EVENT_QUEUE_MAX:
                    self._dropped += 1
                self._events.append(item)
            else:
                self._diagnostics.inc("remote_telemetry_packets")
                key = _remote_packet_key(gateway_id, packet)
                if key in self._telemetry:
                    self._diagnostics.inc("remote_coalesced_replacements")
                    self._telemetry.pop(key, None)
                elif len(self._telemetry) >= REMOTE_PACKET_QUEUE_MAX:
                    self._telemetry.popitem(last=False)
                    self._dropped += 1
                self._telemetry[key] = item

            if self._dropped and (
                self._dropped == 1
                or self._dropped % REMOTE_QUEUE_WARNING_INTERVAL == 0
            ):
                _LOGGER.warning(
                    "Remote ANT+ coalescer dropped %d stale packet(s)",
                    self._dropped,
                )
        self._diagnostics.set_gauge("remote_pending_telemetry", len(self._telemetry))
        self._diagnostics.set_gauge("remote_pending_events", len(self._events))
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=2.0)

    def _take_pending(self) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, dict[str, Any]]]]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
            telemetry = list(self._telemetry.values())
            self._telemetry.clear()
            self._wake.clear()
        return events, telemetry

    def _decode_item(self, item: tuple[str, dict[str, Any]]) -> None:
        gateway_id, packet = item
        started = time.perf_counter()
        try:
            _process_remote_packet(self._receiver, packet, gateway_id)
        except (KeyError, TypeError, ValueError) as err:
            self._diagnostics.inc("remote_invalid_packets")
            _LOGGER.warning(
                "Ignoring invalid ANT+ packet from gateway %s: %s",
                gateway_id,
                err,
            )
        except Exception:
            self._diagnostics.inc("remote_decode_exceptions")
            _LOGGER.exception(
                "Unexpected error decoding ANT+ packet from gateway %s",
                gateway_id,
            )
        finally:
            elapsed = time.perf_counter() - started
            self._diagnostics.inc("remote_packets_decoded")
            self._diagnostics.add_time("remote_decode_dispatch_total", elapsed)

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._wake.wait(timeout=0.5):
                continue
            # Give a short RF window time to collapse repeated telemetry.
            if self._stop.wait(REMOTE_WORKER_COALESCE_WINDOW):
                return
            events, telemetry = self._take_pending()
            for item in events:
                self._decode_item(item)
            for item in telemetry:
                self._decode_item(item)


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

        receiver.diagnostics.inc("remote_bus_events")
        receiver.diagnostics.inc("remote_bus_packets", len(packets))

        # Never decode ANT packets in Home Assistant's event loop. The remote
        # gateway can deliver hundreds of packets per second from multi-profile
        # devices such as Stryd; enqueue only and let the dedicated worker do
        # validation, OpenANT parsing and receiver updates.
        active_adapters: set[str] = set()
        for packet in packets:
            if isinstance(packet, dict):
                adapter_id = str(packet.get("adapter_id", "")).strip()
                if adapter_id:
                    active_adapters.add(adapter_id)
                packet_worker.enqueue(gateway_id, packet)

        # Receiving RF data is itself authoritative proof that this remote
        # physical adapter is capturing. This closes the race where a slow ANT
        # handshake can outlive HA's optimistic Capture confirmation timeout.
        for adapter_id in active_adapters:
            adapter_manager.update_remote_capture_state(
                gateway_id,
                adapter_id,
                True,
            )

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
        capture_states = data.get("capture_states")
        if isinstance(capture_states, dict):
            for stable_key, enabled in capture_states.items():
                adapter_manager.update_remote_capture_state(
                    gateway_id, str(stable_key), bool(enabled)
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
        capture_states = data.get("capture_states")
        if isinstance(capture_states, dict):
            for stable_key, enabled in capture_states.items():
                adapter_manager.update_remote_capture_state(
                    gateway_id, str(stable_key), bool(enabled)
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
