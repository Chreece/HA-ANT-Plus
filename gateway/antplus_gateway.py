#!/usr/bin/env python3
"""Remote ANT+ gateway for HA ANT+."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import queue
import socket
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import websockets
from openant.devices import ANTPLUS_NETWORK_KEY
from openant.easy.channel import Channel
from openant.easy.node import Node

ANTPLUS_NETWORK_NUMBER = 0
ANTPLUS_RF_FREQUENCY = 57
PACKET_EVENT = "antplus_remote_packet"
HELLO_EVENT = "antplus_gateway_hello"
CAPTURE_STATE_EVENT = "antplus_capture_state"
SUPPORTED_USB_IDS = {("0FCF", "1008"), ("0FCF", "1009")}

_LOGGER = logging.getLogger("ha_antplus_gateway")


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
    if parsed.scheme == "http":
        scheme = "ws"
    elif parsed.scheme == "https":
        scheme = "wss"
    else:
        raise ValueError("HA_URL must begin with http:// or https://")
    return f"{scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/api/websocket"


def detect_ant_adapter() -> dict[str, Any] | None:
    """Return metadata for the first supported ANT USB adapter in Linux sysfs."""
    root = Path("/sys/bus/usb/devices")
    if not root.exists():
        return None

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
                value = (device_path / name).read_text().strip()
            except (OSError, UnicodeError):
                return None
            return value or None

        return {
            "vid": vid,
            "pid": pid,
            "serial": read_optional("serial"),
            "manufacturer": read_optional("manufacturer"),
            "product": read_optional("product"),
            "path": str(device_path),
        }

    return None


class AntScanner:
    def __init__(self, packet_queue: queue.Queue[dict[str, Any]]) -> None:
        self.packet_queue = packet_queue
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._node: Node | None = None
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self.start() if enabled else self.stop()

    def start(self) -> None:
        with self._lock:
            self._enabled = True
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run,
                name="antplus-gateway-receiver",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            node = self._node
        if node:
            try:
                node.stop()
            except Exception:
                _LOGGER.debug("Error stopping ANT node", exc_info=True)

    def _on_data(self, data: Any) -> None:
        if not self._enabled or len(data) < 13:
            return

        packet = {
            "device_id": int(data[9]) | (int(data[10]) << 8),
            "device_type": int(data[11]),
            "transmission_type": int(data[12]),
            "payload": bytes(int(v) & 0xFF for v in data[:8]).hex(),
        }
        try:
            self.packet_queue.put_nowait(packet)
        except queue.Full:
            _LOGGER.warning("Packet queue full; dropping ANT packet")

    def _run(self) -> None:
        try:
            node = Node()
            self._node = node
            node.set_network_key(ANTPLUS_NETWORK_NUMBER, ANTPLUS_NETWORK_KEY)

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

            _LOGGER.info("ANT+ gateway capture started")
            node.start()

        except Exception as err:
            _LOGGER.exception("ANT+ scanner error: %s", err)
        finally:
            self._node = None
            _LOGGER.info("ANT+ gateway capture stopped")


class HAConnection:
    def __init__(
        self,
        settings: Settings,
        scanner: AntScanner,
        packet_queue: queue.Queue[dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.scanner = scanner
        self.packet_queue = packet_queue
        self.next_id = 1
        self.capture_known = False

    async def send(self, ws, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["id"] = self.next_id
        self.next_id += 1
        await ws.send(json.dumps(payload))

    async def authenticate(self, ws) -> None:
        msg = json.loads(await ws.recv())
        if msg.get("type") != "auth_required":
            raise RuntimeError("Unexpected HA WebSocket handshake")

        await ws.send(
            json.dumps(
                {
                    "type": "auth",
                    "access_token": self.settings.token,
                }
            )
        )

        msg = json.loads(await ws.recv())
        if msg.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant authentication failed")

    async def sender(self, ws) -> None:
        while True:
            await asyncio.sleep(self.settings.batch_interval)

            if not self.capture_known or not self.scanner.enabled:
                continue

            packets: list[dict[str, Any]] = []
            while len(packets) < 250:
                try:
                    packets.append(self.packet_queue.get_nowait())
                except queue.Empty:
                    break

            if packets:
                await self.send(
                    ws,
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
        adapter = detect_ant_adapter()

        if adapter:
            _LOGGER.info(
                "Detected ANT USB adapter %s:%s serial=%s",
                adapter["vid"],
                adapter["pid"],
                adapter.get("serial") or "<none>",
            )
        else:
            _LOGGER.warning("No supported ANT USB adapter detected in sysfs")

        async with websockets.connect(
            uri,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            await self.authenticate(ws)
            self.capture_known = False
            self.scanner.set_enabled(False)

            await self.send(
                ws,
                {
                    "type": "subscribe_events",
                    "event_type": CAPTURE_STATE_EVENT,
                },
            )

            hello_data: dict[str, Any] = {
                "gateway_id": self.settings.gateway_id,
            }
            if adapter:
                hello_data["adapter"] = adapter

            await self.send(
                ws,
                {
                    "type": "fire_event",
                    "event_type": HELLO_EVENT,
                    "event_data": hello_data,
                },
            )

            sender_task = asyncio.create_task(self.sender(ws))

            try:
                async for raw in ws:
                    msg = json.loads(raw)

                    if msg.get("type") != "event":
                        continue

                    event = msg.get("event") or {}
                    if event.get("event_type") != CAPTURE_STATE_EVENT:
                        continue

                    data = event.get("data") or {}
                    target = data.get("gateway_id")
                    if target and target != self.settings.gateway_id:
                        continue

                    enabled = bool(data.get("enabled", False))
                    self.capture_known = True

                    if enabled != self.scanner.enabled:
                        _LOGGER.info(
                            "Global Capture -> %s",
                            "ON" if enabled else "OFF",
                        )
                        self.scanner.set_enabled(enabled)

            finally:
                sender_task.cancel()

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_session()
            except Exception as err:
                _LOGGER.warning("HA connection lost: %s", err)

            self.scanner.set_enabled(False)
            await asyncio.sleep(self.settings.reconnect_delay)


async def amain() -> None:
    settings = load_settings()
    packet_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10000)
    scanner = AntScanner(packet_queue)
    _LOGGER.info("Starting HA ANT+ gateway %s", settings.gateway_id)
    await HAConnection(settings, scanner, packet_queue).run_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
