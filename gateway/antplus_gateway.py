#!/usr/bin/env python3
"""Remote ANT+ gateway with per-physical-adapter capture."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import queue
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import usb.core
import usb.util
import websockets

from openant.base import ant as ant_module
from openant.base import driver as driver_module
from openant.base.driver import USB2Driver, USB3Driver
from openant.devices import ANTPLUS_NETWORK_KEY
from openant.easy.channel import Channel
from openant.easy.node import Node

ANTPLUS_NETWORK_NUMBER = 0
ANTPLUS_RF_FREQUENCY = 57

PACKET_EVENT = "antplus_remote_packet"
HELLO_EVENT = "antplus_gateway_hello"
STATUS_EVENT = "antplus_gateway_status"
CAPTURE_EVENT = "antplus_adapter_capture"
CAPTURE_STATE_EVENT = "antplus_adapter_capture_state"

SUPPORTED_USB_IDS = {
    ("0FCF", "1008"),
    ("0FCF", "1009"),
}

USB_RESCAN_INTERVAL = 5.0
HEARTBEAT_INTERVAL = 15.0
CAPTURE_START_ATTEMPTS = 3
CAPTURE_RETRY_DELAY = 2.0

_LOGGER = logging.getLogger("ha_antplus_gateway")
_NODE_CREATE_LOCK = threading.Lock()


@dataclass(frozen=True)
class Settings:
    ha_url: str
    token: str
    gateway_id: str
    batch_interval: float
    reconnect_delay: float


def load_settings() -> Settings:
    ha_url = os.environ.get("HA_URL", "").strip().rstrip("/")
    token = os.environ.get("HA_TOKEN", "").strip()
    gateway_id = os.environ.get("GATEWAY_ID", socket.gethostname()).strip()

    if not ha_url:
        raise SystemExit("HA_URL is required")
    if not token:
        raise SystemExit("HA_TOKEN is required")
    if not gateway_id:
        raise SystemExit("GATEWAY_ID may not be empty")

    return Settings(
        ha_url=ha_url,
        token=token,
        gateway_id=gateway_id,
        batch_interval=float(os.environ.get("BATCH_INTERVAL", "0.25")),
        reconnect_delay=float(os.environ.get("RECONNECT_DELAY", "5")),
    )


def websocket_url(ha_url: str) -> str:
    parsed = urlparse(ha_url)
    scheme = "ws" if parsed.scheme == "http" else "wss"
    if parsed.scheme not in ("http", "https"):
        raise ValueError("HA_URL must begin with http:// or https://")
    return f"{scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/api/websocket"


class _PhysicalSelectedMixin:
    TARGET_BUS: int | None = None
    TARGET_ADDRESS: int | None = None

    def open(self) -> None:
        original_find = driver_module.usb.core.find
        target_bus = self.TARGET_BUS
        target_address = self.TARGET_ADDRESS

        def selected_find(*args, **kwargs):
            devices = original_find(
                idVendor=kwargs.get("idVendor", self.ID_VENDOR),
                idProduct=kwargs.get("idProduct", self.ID_PRODUCT),
                find_all=True,
            )
            if devices is None:
                return None

            for device in devices:
                if (
                    getattr(device, "bus", None) == target_bus
                    and getattr(device, "address", None) == target_address
                ):
                    return device

            return None

        driver_module.usb.core.find = selected_find
        try:
            super().open()
        finally:
            driver_module.usb.core.find = original_find


class PhysicalUSB2Driver(_PhysicalSelectedMixin, USB2Driver):
    pass


class PhysicalUSB3Driver(_PhysicalSelectedMixin, USB3Driver):
    pass


@contextmanager
def _selected_driver(
    pid: str,
    bus: int,
    address: int,
):
    pid_int = int(pid, 16)

    if pid_int == USB2Driver.ID_PRODUCT:
        driver_cls = PhysicalUSB2Driver
    elif pid_int == USB3Driver.ID_PRODUCT:
        driver_cls = PhysicalUSB3Driver
    else:
        raise ValueError(f"Unsupported ANT USB product id {pid}")

    class SelectedDriver(driver_cls):
        TARGET_BUS = bus
        TARGET_ADDRESS = address

    original = ant_module.find_driver
    ant_module.find_driver = lambda: SelectedDriver()
    try:
        yield
    finally:
        ant_module.find_driver = original


def create_selected_node(
    pid: str,
    bus: int,
    address: int,
) -> Node:
    with _NODE_CREATE_LOCK:
        with _selected_driver(pid, bus, address):
            return Node()


def detect_ant_adapters() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    root = Path("/sys/bus/usb/devices")
    if not root.exists():
        return result

    for device_path in sorted(root.glob("*")):
        try:
            vid = (device_path / "idVendor").read_text().strip().upper()
            pid = (device_path / "idProduct").read_text().strip().upper()
        except (OSError, UnicodeError):
            continue

        if (vid, pid) not in SUPPORTED_USB_IDS:
            continue

        def read_optional(name: str) -> str | None:
            try:
                return (device_path / name).read_text().strip() or None
            except (OSError, UnicodeError):
                return None

        result.append(
            {
                "vid": vid,
                "pid": pid,
                "serial": read_optional("serial"),
                "manufacturer": read_optional("manufacturer"),
                "product": read_optional("product"),
                "path": str(device_path),
                "bus": int(read_optional("busnum") or 0) or None,
                "address": int(read_optional("devnum") or 0) or None,
            }
        )
    return result


def stable_key(adapter: dict[str, Any]) -> str:
    serial = adapter.get("serial")
    if not serial:
        raise ValueError("Remote per-adapter capture requires a USB serial number")
    return f"{adapter['vid'].upper()}:{adapter['pid'].upper()}:{str(serial).strip()}"


class AntScanner:
    def __init__(
        self,
        adapter: dict[str, Any],
        packet_queue: queue.Queue[dict[str, Any]],
        state_queue: queue.Queue[dict[str, Any]],
    ) -> None:
        self.adapter = adapter
        self.adapter_id = stable_key(adapter)
        self.packet_queue = packet_queue
        self.state_queue = state_queue
        self._node = None
        self._thread: threading.Thread | None = None
        self._enabled = False
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(
            self._enabled
            and thread is not None
            and thread.is_alive()
            and self._node is not None
        )

    def start(self) -> None:
        with self._lock:
            self._enabled = True
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run,
                name=f"antplus-{self.adapter.get('serial') or self.adapter['pid']}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            node = self._node
        if node is not None:
            try:
                node.stop()
            except Exception:
                _LOGGER.debug("Error stopping ANT node", exc_info=True)

    def _refresh_runtime_adapter(self) -> None:
        """Refresh bus/address without changing physical adapter identity."""
        for candidate in detect_ant_adapters():
            try:
                candidate_id = stable_key(candidate)
            except ValueError:
                continue

            if candidate_id == self.adapter_id:
                self.adapter = candidate
                return

        raise RuntimeError(
            f"Physical ANT USB adapter {self.adapter_id} is not currently present"
        )

    def _report_state(
        self,
        enabled: bool,
        error: str | None = None,
    ) -> None:
        try:
            self.state_queue.put_nowait(
                {
                    "adapter_id": self.adapter_id,
                    "enabled": bool(enabled),
                    "error": error,
                }
            )
        except queue.Full:
            _LOGGER.warning("Capture-state queue full for %s", self.adapter_id)

    def _on_data(self, data: Any) -> None:
        if not self._enabled or len(data) < 13:
            return
        packet = {
            "adapter_id": self.adapter_id,
            "device_id": int(data[9]) | (int(data[10]) << 8),
            "device_type": int(data[11]),
            "transmission_type": int(data[12]),
            "payload": bytes(int(value) & 0xFF for value in data[:8]).hex(),
        }
        try:
            self.packet_queue.put_nowait(packet)
        except queue.Full:
            _LOGGER.warning("Packet queue full; dropping ANT packet")

    def _run(self) -> None:
        last_error: Exception | None = None

        try:
            for attempt in range(1, CAPTURE_START_ATTEMPTS + 1):
                if not self._enabled:
                    return

                node = None

                try:
                    self._refresh_runtime_adapter()

                    bus = self.adapter.get("bus")
                    address = self.adapter.get("address")
                    if bus is None or address is None:
                        raise RuntimeError(
                            f"USB bus/address unavailable for {self.adapter_id}"
                        )

                    _LOGGER.info(
                        "Starting capture on %s (attempt %d/%d, bus=%s address=%s)",
                        self.adapter_id,
                        attempt,
                        CAPTURE_START_ATTEMPTS,
                        bus,
                        address,
                    )

                    node = create_selected_node(
                        self.adapter["pid"],
                        int(bus),
                        int(address),
                    )
                    self._node = node

                    node.set_network_key(
                        ANTPLUS_NETWORK_NUMBER,
                        ANTPLUS_NETWORK_KEY,
                    )

                    channel = node.new_channel(
                        Channel.Type.BIDIRECTIONAL_RECEIVE,
                        ANTPLUS_NETWORK_NUMBER,
                        0x01,
                    )
                    channel.on_broadcast_data = self._on_data
                    channel.on_burst_data = self._on_data
                    channel.on_acknowledge = self._on_data
                    channel.set_id(0, 0, 0)
                    channel.enable_extended_messages(1)
                    channel.set_rf_freq(ANTPLUS_RF_FREQUENCY)
                    channel.open_rx_scan_mode()

                    if not self._enabled:
                        try:
                            node.stop()
                        except Exception:
                            pass
                        return

                    _LOGGER.info(
                        "Capture started on adapter %s",
                        self.adapter_id,
                    )
                    self._report_state(True)

                    node.start()
                    return

                except Exception as err:
                    last_error = err
                    self._node = None

                    if node is not None:
                        try:
                            node.stop()
                        except Exception:
                            _LOGGER.debug(
                                "Error closing failed ANT node for %s",
                                self.adapter_id,
                                exc_info=True,
                            )

                    if not self._enabled:
                        return

                    if attempt < CAPTURE_START_ATTEMPTS:
                        _LOGGER.warning(
                            "Capture handshake failed on %s (attempt %d/%d): %s; "
                            "retrying in %.1fs",
                            self.adapter_id,
                            attempt,
                            CAPTURE_START_ATTEMPTS,
                            err,
                            CAPTURE_RETRY_DELAY,
                        )
                        time.sleep(CAPTURE_RETRY_DELAY)
                        continue

                    _LOGGER.error(
                        "Capture failed on adapter %s after %d attempts: %s",
                        self.adapter_id,
                        CAPTURE_START_ATTEMPTS,
                        err,
                    )

            self._enabled = False
            self._report_state(
                False,
                str(last_error) if last_error is not None else "Capture failed",
            )

        finally:
            self._node = None

            if not self._enabled:
                self._report_state(False)

            _LOGGER.info(
                "Capture stopped on adapter %s",
                self.adapter_id,
            )


class HAConnection:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.packet_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10000)
        self.state_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        self.next_id = 1
        self._adapters: dict[str, dict[str, Any]] = {}
        self._scanners: dict[str, AntScanner] = {}
        self._desired: dict[str, bool] = {}
        self._missing_since: dict[str, float] = {}
        self._last_status_sent = 0.0

    async def send(self, websocket, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["id"] = self.next_id
        self.next_id += 1
        await websocket.send(json.dumps(payload))

    async def authenticate(self, websocket) -> None:
        message = json.loads(await websocket.recv())
        if message.get("type") != "auth_required":
            raise RuntimeError("Unexpected HA WebSocket handshake")
        await websocket.send(
            json.dumps(
                {
                    "type": "auth",
                    "access_token": self.settings.token,
                }
            )
        )
        message = json.loads(await websocket.recv())
        if message.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant authentication failed")
        _LOGGER.info("Authenticated with Home Assistant")

    def _stop_adapter(self, adapter_id: str) -> None:
        scanner = self._scanners.pop(adapter_id, None)
        if scanner is not None:
            scanner.stop()

    def _sync_adapter(self, adapter_id: str) -> None:
        adapter = self._adapters.get(adapter_id)
        desired = self._desired.get(adapter_id, False)

        if adapter is None or not desired:
            self._stop_adapter(adapter_id)
            return

        scanner = self._scanners.get(adapter_id)

        if scanner is None:
            scanner = AntScanner(
                adapter,
                self.packet_queue,
                self.state_queue,
            )
            self._scanners[adapter_id] = scanner
            scanner.start()
            return

        if not scanner.running:
            scanner.adapter = adapter
            scanner.start()

    async def refresh_adapters(self, websocket, *, force: bool = False) -> None:
        loop = asyncio.get_running_loop()
        detected = await loop.run_in_executor(None, detect_ant_adapters)
        current = {}
        for adapter in detected:
            try:
                current[stable_key(adapter)] = adapter
            except ValueError:
                _LOGGER.warning("Ignoring ANT USB adapter without serial: %s", adapter)

        now = time.monotonic()
        previous = dict(self._adapters)

        for adapter_id in current:
            self._missing_since.pop(adapter_id, None)

        for adapter_id, adapter in previous.items():
            if adapter_id in current:
                continue

            missing_since = self._missing_since.setdefault(adapter_id, now)
            if now - missing_since <= 20.0:
                current[adapter_id] = adapter
                continue

            self._missing_since.pop(adapter_id, None)
            self._stop_adapter(adapter_id)

        changed = current != self._adapters
        self._adapters = current

        for adapter_id in current:
            self._sync_adapter(adapter_id)

        if (
            not force
            and not changed
            and now - self._last_status_sent < HEARTBEAT_INTERVAL
        ):
            return

        self._last_status_sent = now
        await self.send(
            websocket,
            {
                "type": "fire_event",
                "event_type": STATUS_EVENT,
                "event_data": {
                    "gateway_id": self.settings.gateway_id,
                    "adapters": list(current.values()),
                },
            },
        )

        if changed:
            _LOGGER.info(
                "ANT USB adapters: %s",
                ", ".join(sorted(current)) or "none",
            )

    async def status_loop(self, websocket) -> None:
        while True:
            await self.refresh_adapters(websocket)
            await asyncio.sleep(USB_RESCAN_INTERVAL)

    async def capture_state_sender(self, websocket) -> None:
        while True:
            await asyncio.sleep(0.1)
            while True:
                try:
                    state = self.state_queue.get_nowait()
                except queue.Empty:
                    break
                await self.send(
                    websocket,
                    {
                        "type": "fire_event",
                        "event_type": CAPTURE_STATE_EVENT,
                        "event_data": {
                            "gateway_id": self.settings.gateway_id,
                            **state,
                        },
                    },
                )

    async def packet_sender(self, websocket) -> None:
        while True:
            await asyncio.sleep(self.settings.batch_interval)
            packets: list[dict[str, Any]] = []
            while len(packets) < 250:
                try:
                    packets.append(self.packet_queue.get_nowait())
                except queue.Empty:
                    break
            if packets:
                await self.send(
                    websocket,
                    {
                        "type": "fire_event",
                        "event_type": PACKET_EVENT,
                        "event_data": {
                            "gateway_id": self.settings.gateway_id,
                            "packets": packets,
                        },
                    },
                )

    async def run_session(self) -> None:
        uri = websocket_url(self.settings.ha_url)

        async with websockets.connect(
            uri,
            ping_interval=20,
            ping_timeout=20,
        ) as websocket:
            await self.authenticate(websocket)
            self._desired.clear()

            await self.send(
                websocket,
                {
                    "type": "subscribe_events",
                    "event_type": CAPTURE_EVENT,
                },
            )

            await self.refresh_adapters(websocket, force=True)

            await self.send(
                websocket,
                {
                    "type": "fire_event",
                    "event_type": HELLO_EVENT,
                    "event_data": {
                        "gateway_id": self.settings.gateway_id,
                        "adapters": list(self._adapters.values()),
                    },
                },
            )

            packet_task = asyncio.create_task(self.packet_sender(websocket))
            status_task = asyncio.create_task(self.status_loop(websocket))
            capture_state_task = asyncio.create_task(
                self.capture_state_sender(websocket)
            )

            try:
                async for raw in websocket:
                    message = json.loads(raw)
                    if message.get("type") != "event":
                        continue

                    event = message.get("event") or {}
                    if event.get("event_type") != CAPTURE_EVENT:
                        continue

                    data = event.get("data") or {}
                    if data.get("gateway_id") != self.settings.gateway_id:
                        continue

                    adapter_id = str(data.get("adapter_id", "")).strip()
                    if not adapter_id:
                        continue

                    enabled = bool(data.get("enabled", False))
                    self._desired[adapter_id] = enabled
                    _LOGGER.info(
                        "Capture %s -> %s",
                        adapter_id,
                        "ON" if enabled else "OFF",
                    )
                    self._sync_adapter(adapter_id)
            finally:
                packet_task.cancel()
                status_task.cancel()
                capture_state_task.cancel()
                for task in (
                    packet_task,
                    status_task,
                    capture_state_task,
                ):
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                for adapter_id in list(self._scanners):
                    self._stop_adapter(adapter_id)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_session()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning("HA connection lost: %s", err)

            for adapter_id in list(self._scanners):
                self._stop_adapter(adapter_id)

            await asyncio.sleep(self.settings.reconnect_delay)


async def amain() -> None:
    settings = load_settings()
    _LOGGER.info("Starting HA ANT+ gateway %s", settings.gateway_id)
    await HAConnection(settings).run_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
