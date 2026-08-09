"""Physical ANT USB adapter identity, presence and per-adapter capture."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import logging
from pathlib import Path
import threading
import time
from typing import Any

from openant.devices import ANTPLUS_NETWORK_KEY
from openant.easy.channel import Channel

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, REMOTE_ADAPTER_CAPTURE_EVENT
from .usb_selected import create_selected_node

_LOGGER = logging.getLogger(__name__)

SUPPORTED_USB_IDS = {
    ("0FCF", "1008"),
    ("0FCF", "1009"),
}

ANTPLUS_NETWORK_NUMBER = 0
ANTPLUS_RF_FREQUENCY = 57

KNOWN_ADAPTERS_KEY = "known_adapters"
LEGACY_ADAPTER_IDENTIFIER = (DOMAIN, "usb_adapter")

LOCAL_SCAN_INTERVAL = timedelta(seconds=5)
REMOTE_EXPIRE_INTERVAL = timedelta(seconds=15)
REMOTE_EXPIRE_SECONDS = 45.0

AdapterCallback = Callable[[str], None]


@dataclass(slots=True)
class AntUsbAdapter:
    """Stable description of one physical ANT USB adapter."""

    vid: str
    pid: str
    serial: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    path: str | None = None
    source: str | None = None
    gateway_id: str | None = None

    def __post_init__(self) -> None:
        self.vid = self.vid.upper().zfill(4)
        self.pid = self.pid.upper().zfill(4)
        if self.serial is not None:
            self.serial = self.serial.rstrip("\x00").strip() or None
        if self.manufacturer is not None:
            self.manufacturer = self.manufacturer.rstrip("\x00").strip() or None
        if self.product is not None:
            self.product = self.product.rstrip("\x00").strip() or None

    @property
    def stable_key(self) -> str:
        if self.serial:
            return f"{self.vid}:{self.pid}:{self.serial}"

        fingerprint_source = "|".join(
            (
                self.vid,
                self.pid,
                self.manufacturer or "",
                self.product or "",
                self.path or "",
            )
        )
        digest = hashlib.sha256(
            fingerprint_source.encode("utf-8")
        ).hexdigest()[:16]
        return f"{self.vid}:{self.pid}:noserial:{digest}"

    @property
    def ha_identifier(self) -> tuple[str, str]:
        return (DOMAIN, f"usb_adapter:{self.stable_key}")

    @property
    def name(self) -> str:
        base = self.product or "ANT+ USB Adapter"
        if self.serial:
            return f"{base} {self.serial}"
        return base

    def identity_storage(self) -> dict[str, Any]:
        return {
            "vid": self.vid,
            "pid": self.pid,
            "serial": self.serial,
            "manufacturer": self.manufacturer,
            "product": self.product,
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AntUsbAdapter":
        return cls(
            vid=str(data["vid"]),
            pid=str(data["pid"]),
            serial=data.get("serial"),
            manufacturer=data.get("manufacturer"),
            product=data.get("product"),
            path=data.get("path"),
            source=data.get("source"),
            gateway_id=data.get("gateway_id"),
        )


@dataclass(slots=True)
class AdapterPresence:
    adapter: AntUsbAdapter
    local_present: bool = False
    remote_gateways: dict[str, float] | None = None
    capture_enabled: bool = False

    def __post_init__(self) -> None:
        if self.remote_gateways is None:
            self.remote_gateways = {}

    @property
    def available(self) -> bool:
        return self.local_present or bool(self.remote_gateways)

    @property
    def sources(self) -> list[str]:
        result: list[str] = []
        if self.local_present:
            result.append("local")
        result.extend(
            f"remote:{gateway_id}"
            for gateway_id in sorted(self.remote_gateways or {})
        )
        return result

    @property
    def connection(self) -> str:
        if self.local_present and self.remote_gateways:
            return "Local + " + ", ".join(sorted(self.remote_gateways))
        if self.local_present:
            return "Local"
        if self.remote_gateways:
            return ", ".join(sorted(self.remote_gateways))
        return "Unavailable"


def scan_linux_ant_adapters() -> list[AntUsbAdapter]:
    adapters: list[AntUsbAdapter] = []
    root = Path("/sys/bus/usb/devices")

    if not root.exists():
        return adapters

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

        adapters.append(
            AntUsbAdapter(
                vid=vid,
                pid=pid,
                serial=read_optional("serial"),
                manufacturer=read_optional("manufacturer"),
                product=read_optional("product"),
                path=str(device_path),
                source="local",
            )
        )

    return adapters


class LocalAdapterScanner:
    """One OpenANT scan node bound to one physical local USB adapter."""

    def __init__(self, adapter: AntUsbAdapter, receiver) -> None:
        self.adapter = adapter
        self.receiver = receiver
        self._thread: threading.Thread | None = None
        self._node = None
        self._lock = threading.RLock()
        self._enabled = False

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(self._enabled and thread and thread.is_alive())

    def start(self) -> None:
        with self._lock:
            self._enabled = True
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run,
                name=f"antplus-{self.adapter.serial or self.adapter.pid}",
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
                _LOGGER.debug(
                    "Error stopping local ANT+ adapter %s",
                    self.adapter.stable_key,
                    exc_info=True,
                )

    def _on_data(self, data: Any) -> None:
        if not self._enabled or len(data) < 13:
            return
        self.receiver.process_packet(
            device_id=int(data[9]) | (int(data[10]) << 8),
            device_type=int(data[11]),
            transmission_type=int(data[12]),
            payload=bytes(int(value) & 0xFF for value in data[:8]),
            source=f"local:{self.adapter.stable_key}",
        )

    def _run(self) -> None:
        try:
            node = create_selected_node(
                self.adapter.vid,
                self.adapter.pid,
                self.adapter.serial,
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

            _LOGGER.info(
                "Capture started on local ANT USB adapter %s",
                self.adapter.stable_key,
            )
            node.start()
        except Exception:
            _LOGGER.exception(
                "Capture failed on local ANT USB adapter %s",
                self.adapter.stable_key,
            )
        finally:
            self._node = None
            _LOGGER.info(
                "Capture stopped on local ANT USB adapter %s",
                self.adapter.stable_key,
            )


class AntAdapterManager:
    """Track physical adapters and route capture commands to that adapter."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, receiver) -> None:
        self.hass = hass
        self.entry = entry
        self.receiver = receiver
        self._records: dict[str, AdapterPresence] = {}
        self._callbacks: list[AdapterCallback] = []
        self._remote_gateway_last_seen: dict[str, float] = {}
        self._local_scanners: dict[str, LocalAdapterScanner] = {}
        self._unsubs: list[Callable[[], None]] = []

    @property
    def records(self) -> dict[str, AdapterPresence]:
        return self._records

    def get(self, stable_key: str) -> AdapterPresence | None:
        return self._records.get(stable_key)

    def add_callback(self, callback: AdapterCallback) -> Callable[[], None]:
        self._callbacks.append(callback)

        def remove() -> None:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

        return remove

    def _notify(self, stable_key: str) -> None:
        for callback in tuple(self._callbacks):
            try:
                callback(stable_key)
            except Exception:
                _LOGGER.debug("ANT+ adapter callback failed", exc_info=True)

    def _known_adapters(self) -> dict[str, dict[str, Any]]:
        raw = self.entry.data.get(KNOWN_ADAPTERS_KEY, {})
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): value
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    def _persist_record(self, record: AdapterPresence) -> None:
        known = self._known_adapters()
        stored = record.adapter.identity_storage()
        stored["capture_enabled"] = record.capture_enabled

        if known.get(record.adapter.stable_key) == stored:
            return

        known[record.adapter.stable_key] = stored
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, KNOWN_ADAPTERS_KEY: known},
        )

    def _merge_or_register_device(self, adapter: AntUsbAdapter) -> None:
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)

        identifier = adapter.ha_identifier
        physical = device_registry.async_get_device_by_identifier(
            identifier,
            self.entry.entry_id,
        )
        legacy = device_registry.async_get_device_by_identifier(
            LEGACY_ADAPTER_IDENTIFIER,
            self.entry.entry_id,
        )

        if physical is None and legacy is not None:
            device_registry.async_update_device(
                legacy.id,
                new_identifiers={identifier},
                name=adapter.name,
                manufacturer=adapter.manufacturer or "Dynastream / Garmin",
                model=adapter.product or f"ANT USB {adapter.vid}:{adapter.pid}",
                serial_number=adapter.serial,
            )
            physical = device_registry.async_get_device_by_identifier(
                identifier,
                self.entry.entry_id,
            )

        if physical is None:
            physical = device_registry.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={identifier},
                name=adapter.name,
                manufacturer=adapter.manufacturer or "Dynastream / Garmin",
                model=adapter.product or f"ANT USB {adapter.vid}:{adapter.pid}",
                serial_number=adapter.serial,
            )
        else:
            device_registry.async_update_device(
                physical.id,
                name=adapter.name,
                manufacturer=adapter.manufacturer or "Dynastream / Garmin",
                model=adapter.product or f"ANT USB {adapter.vid}:{adapter.pid}",
                serial_number=adapter.serial,
            )

        legacy = device_registry.async_get_device_by_identifier(
            LEGACY_ADAPTER_IDENTIFIER,
            self.entry.entry_id,
        )
        if legacy is not None and physical is not None and legacy.id != physical.id:
            for entity in list(entity_registry.entities.values()):
                if entity.device_id == legacy.id:
                    entity_registry.async_update_entity(
                        entity.entity_id,
                        device_id=physical.id,
                    )
            device_registry.async_remove_device(legacy.id)

    def _ensure_record(
        self,
        adapter: AntUsbAdapter,
        *,
        saved_capture: bool | None = None,
    ) -> AdapterPresence:
        record = self._records.get(adapter.stable_key)
        if record is None:
            record = AdapterPresence(
                adapter=adapter,
                capture_enabled=bool(saved_capture),
            )
            self._records[adapter.stable_key] = record
        else:
            record.adapter = adapter

        self._merge_or_register_device(adapter)
        self._persist_record(record)
        return record

    async def async_start(self) -> None:
        for data in self._known_adapters().values():
            try:
                adapter = AntUsbAdapter.from_mapping(data)
            except (KeyError, TypeError, ValueError):
                continue
            self._ensure_record(
                adapter,
                saved_capture=bool(data.get("capture_enabled", False)),
            )

        await self.async_refresh_local()

        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_local_tick,
                LOCAL_SCAN_INTERVAL,
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_expire_tick,
                REMOTE_EXPIRE_INTERVAL,
            )
        )

    def stop(self) -> None:
        for scanner in tuple(self._local_scanners.values()):
            scanner.stop()
        self._local_scanners.clear()

        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _async_local_tick(self, _now) -> None:
        await self.async_refresh_local()

    async def _async_expire_tick(self, _now) -> None:
        self.expire_remote_gateways()

    def _sync_local_capture(self, stable_key: str) -> None:
        record = self._records.get(stable_key)
        if record is None:
            return

        scanner = self._local_scanners.get(stable_key)

        if record.local_present and record.capture_enabled:
            if scanner is None:
                scanner = LocalAdapterScanner(record.adapter, self.receiver)
                self._local_scanners[stable_key] = scanner
            scanner.start()
            return

        if scanner is not None:
            scanner.stop()
            self._local_scanners.pop(stable_key, None)

    def _send_remote_capture(
        self,
        stable_key: str,
        gateway_id: str,
        enabled: bool,
    ) -> None:
        self.hass.bus.async_fire(
            REMOTE_ADAPTER_CAPTURE_EVENT,
            {
                "gateway_id": gateway_id,
                "adapter_id": stable_key,
                "enabled": enabled,
            },
        )

    async def async_set_capture(self, stable_key: str, enabled: bool) -> None:
        record = self._records.get(stable_key)
        if record is None:
            return

        record.capture_enabled = bool(enabled)
        self._persist_record(record)
        self._sync_local_capture(stable_key)

        for gateway_id in sorted(record.remote_gateways or {}):
            self._send_remote_capture(
                stable_key,
                gateway_id,
                record.capture_enabled,
            )

        self._notify(stable_key)

    async def async_refresh_local(self) -> None:
        adapters = await self.hass.async_add_executor_job(
            scan_linux_ant_adapters
        )
        present_keys = {adapter.stable_key for adapter in adapters}

        for adapter in adapters:
            record = self._ensure_record(adapter)
            changed = not record.local_present
            record.local_present = True
            self._sync_local_capture(adapter.stable_key)
            if changed:
                self._notify(adapter.stable_key)

        for stable_key, record in self._records.items():
            if record.local_present and stable_key not in present_keys:
                record.local_present = False
                self._sync_local_capture(stable_key)
                self._notify(stable_key)

    def update_remote_gateway(
        self,
        gateway_id: str,
        adapters: list[AntUsbAdapter],
    ) -> None:
        now = time.monotonic()
        self._remote_gateway_last_seen[gateway_id] = now
        current_keys = {adapter.stable_key for adapter in adapters}

        for stable_key, record in self._records.items():
            if (
                gateway_id in (record.remote_gateways or {})
                and stable_key not in current_keys
            ):
                record.remote_gateways.pop(gateway_id, None)
                self._notify(stable_key)

        for adapter in adapters:
            adapter.source = "remote"
            adapter.gateway_id = gateway_id
            record = self._ensure_record(adapter)
            new_presence = gateway_id not in (record.remote_gateways or {})
            record.remote_gateways[gateway_id] = now

            if new_presence:
                self._send_remote_capture(
                    adapter.stable_key,
                    gateway_id,
                    record.capture_enabled,
                )
                self._notify(adapter.stable_key)

    def expire_remote_gateways(self) -> None:
        now = time.monotonic()
        expired = {
            gateway_id
            for gateway_id, last_seen in self._remote_gateway_last_seen.items()
            if now - last_seen > REMOTE_EXPIRE_SECONDS
        }

        if not expired:
            return

        for gateway_id in expired:
            self._remote_gateway_last_seen.pop(gateway_id, None)

        for stable_key, record in self._records.items():
            changed = False
            for gateway_id in expired:
                if gateway_id in (record.remote_gateways or {}):
                    record.remote_gateways.pop(gateway_id, None)
                    changed = True
            if changed:
                self._notify(stable_key)
