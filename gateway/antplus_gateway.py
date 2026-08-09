#!/usr/bin/env python3
"""Remote ANT+ gateway for HA ANT+."""
from __future__ import annotations

import asyncio, json, logging, os, queue, socket, threading
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
    return Settings(
        ha_url=ha_url,
        token=token,
        gateway_id=gateway_id,
        batch_interval=float(os.environ.get("BATCH_INTERVAL", "0.25")),
        reconnect_delay=float(os.environ.get("RECONNECT_DELAY", "5")),
    )

def websocket_url(ha_url: str) -> str:
    parsed = urlparse(ha_url)
    scheme = "ws" if parsed.scheme == "http" else "wss" if parsed.scheme == "https" else None
    if scheme is None:
        raise ValueError("HA_URL must begin with http:// or https://")
    return f"{scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/api/websocket"

class AntScanner:
    def __init__(self, packet_queue: queue.Queue[dict[str, Any]]) -> None:
        self.packet_queue = packet_queue
        self._lock = threading.RLock()
        self._thread = None
        self._node = None
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
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            node = self._node
        if node:
            try:
                node.stop()
            except Exception:
                pass

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
            ch = node.new_channel(Channel.Type.BIDIRECTIONAL_RECEIVE, ANTPLUS_NETWORK_NUMBER, 0x01)
            ch.on_broadcast_data = self._on_data
            ch.on_burst_data = self._on_data
            ch.on_acknowledge = self._on_data
            ch.set_id(0, 0, 0)
            ch.enable_extended_messages(1)
            ch.set_rf_freq(ANTPLUS_RF_FREQUENCY)
            ch.open_rx_scan_mode()
            _LOGGER.info("ANT+ gateway capture started")
            node.start()
        except Exception as err:
            _LOGGER.exception("ANT+ scanner error: %s", err)
        finally:
            self._node = None
            _LOGGER.info("ANT+ gateway capture stopped")

class HAConnection:
    def __init__(self, settings: Settings, scanner: AntScanner, packet_queue):
        self.settings = settings
        self.scanner = scanner
        self.packet_queue = packet_queue
        self.next_id = 1
        self.capture_known = False

    async def send(self, ws, payload):
        payload = dict(payload)
        payload["id"] = self.next_id
        self.next_id += 1
        await ws.send(json.dumps(payload))

    async def authenticate(self, ws):
        msg = json.loads(await ws.recv())
        if msg.get("type") != "auth_required":
            raise RuntimeError("Unexpected HA WebSocket handshake")
        await ws.send(json.dumps({"type": "auth", "access_token": self.settings.token}))
        msg = json.loads(await ws.recv())
        if msg.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant authentication failed")

    async def sender(self, ws):
        while True:
            await asyncio.sleep(self.settings.batch_interval)
            if not self.capture_known or not self.scanner.enabled:
                continue
            packets = []
            while len(packets) < 250:
                try:
                    packets.append(self.packet_queue.get_nowait())
                except queue.Empty:
                    break
            if packets:
                await self.send(ws, {
                    "type": "fire_event",
                    "event_type": PACKET_EVENT,
                    "event_data": {"gateway_id": self.settings.gateway_id, "packets": packets},
                })

    async def run_session(self):
        uri = websocket_url(self.settings.ha_url)
        async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
            await self.authenticate(ws)
            self.capture_known = False
            self.scanner.set_enabled(False)
            await self.send(ws, {"type": "subscribe_events", "event_type": CAPTURE_STATE_EVENT})
            await self.send(ws, {
                "type": "fire_event",
                "event_type": HELLO_EVENT,
                "event_data": {"gateway_id": self.settings.gateway_id},
            })
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
                        _LOGGER.info("Global Capture -> %s", "ON" if enabled else "OFF")
                        self.scanner.set_enabled(enabled)
            finally:
                sender_task.cancel()

    async def run_forever(self):
        while True:
            try:
                await self.run_session()
            except Exception as err:
                _LOGGER.warning("HA connection lost: %s", err)
            self.scanner.set_enabled(False)
            await asyncio.sleep(self.settings.reconnect_delay)

async def amain():
    settings = load_settings()
    q = queue.Queue(maxsize=10000)
    scanner = AntScanner(q)
    _LOGGER.info("Starting HA ANT+ gateway %s", settings.gateway_id)
    await HAConnection(settings, scanner, q).run_forever()

if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
