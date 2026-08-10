"""Physical ANT USB adapter identity, presence and per-adapter capture."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import asyncio
import hashlib
import logging
from pathlib import Path
import threading
import time
import uuid
from typing import Any

from openant.devices import ANTPLUS_NETWORK_KEY
from openant.easy.channel import Channel

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    REMOTE_ADAPTER_CAPTURE_EVENT,
    REMOTE_ADAPTER_CONTROL_EVENT,
    REMOTE_CONTROL_PROTOCOL,
    REMOTE_CONTROL_TIMEOUT,
)
from .usb_selected import create_selected_node

_LOGGER = logging.getLogger(__name__)

SUPPORTED_USB_IDS = {
    ("0FCF", "1008"),
    ("0FCF", "1009"),
}

ANTPLUS_NETWORK_NUMBER = 0
ANTPLUS_RF_FREQUENCY = 57

KNOWN_ADAPTERS_KEY = "known_adapters"
CAPTURE_STORAGE_VERSION = 1
CAPTURE_STORAGE_KEY = f"{DOMAIN}.capture_states"
LEGACY_ADAPTER_IDENTIFIER = (DOMAIN, "usb_adapter")

LOCAL_SCAN_INTERVAL = timedelta(seconds=5)
REMOTE_EXPIRE_INTERVAL = timedelta(seconds=15)
REMOTE_EXPIRE_SECONDS = 45.0
LOCAL_MISSING_GRACE_SECONDS = 15.0
REMOTE_ADAPTER_MISSING_GRACE_SECONDS = 20.0

# How long HA keeps showing the requested Capture state while waiting
# for the physical adapter/gateway to confirm what actually happened.
CAPTURE_CONFIRM_TIMEOUT_SECONDS = 30.0

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
    bus: int | None = None
    address: int | None = None
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

    @property
    def subentry_name(self) -> str:
        # Host-independent title derived only from USB metadata.
        base = self.product or "ANT+ USB Adapter"

        if self.serial:
            return f"{base} {self.serial}"

        return f"{base} {self.vid}:{self.pid}"

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
            bus=int(data["bus"]) if data.get("bus") is not None else None,
            address=int(data["address"]) if data.get("address") is not None else None,
            source=data.get("source"),
            gateway_id=data.get("gateway_id"),
        )


@dataclass(slots=True)
class AdapterPresence:
    adapter: AntUsbAdapter
    local_present: bool = False
    local_missing_since: float | None = None
    remote_gateways: dict[str, float] | None = None
    remote_missing_since: dict[str, float] | None = None
    desired_capture: bool = False
    local_capture_enabled: bool = False
    remote_capture_states: dict[str, bool] | None = None
    capture_error: str | None = None

    # Transient optimistic UI state. This exists only while HA is waiting
    # for the physical adapter to confirm the requested Capture state.
    pending_capture: bool | None = None
    pending_capture_since: float | None = None

    def __post_init__(self) -> None:
        if self.remote_gateways is None:
            self.remote_gateways = {}
        if self.remote_missing_since is None:
            self.remote_missing_since = {}
        if self.remote_capture_states is None:
            self.remote_capture_states = {}

    @property
    def capture_enabled(self) -> bool:
        return self.local_capture_enabled or any(
            (self.remote_capture_states or {}).values()
        )

    @property
    def displayed_capture(self) -> bool:
        """State exposed by the HA switch.

        While a command is awaiting physical confirmation, expose the
        requested state. Otherwise expose the confirmed physical state.
        """
        if self.pending_capture is not None:
            return self.pending_capture
        return self.capture_enabled

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
                bus=int(read_optional("busnum") or 0) or None,
                address=int(read_optional("devnum") or 0) or None,
                source="local",
            )
        )

    return adapters


class LocalAdapterScanner:
    """One OpenANT scan node bound to one physical local USB adapter."""

    def __init__(
        self,
        adapter: AntUsbAdapter,
        receiver,
        state_callback,
    ) -> None:
        self.adapter = adapter
        self.receiver = receiver
        self.state_callback = state_callback
        self._thread: threading.Thread | None = None
        self._node = None
        self._lock = threading.RLock()
        self._enabled = False
        self._scan_channel = None
        self._control_lock = threading.RLock()

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

    def send_acknowledged(
        self,
        *,
        device_id: int,
        device_type: int,
        transmission_type: int,
        payload: bytes,
        period: int,
    ) -> None:
        """Temporarily leave continuous scan mode and send one paired ACK."""
        with self._control_lock:
            node = self._node
            scan = self._scan_channel
            if not self.running or node is None or scan is None:
                raise RuntimeError(f"ANT USB adapter {self.adapter.stable_key} is not capturing")
            control = None
            try:
                # Continuous RX scan occupies the radio. Keep the node alive,
                # briefly close scan mode, transmit, then immediately resume.
                scan.close()
                control = node.new_channel(
                    Channel.Type.BIDIRECTIONAL_RECEIVE,
                    ANTPLUS_NETWORK_NUMBER,
                    0x01,
                )
                control.set_id(device_id, device_type, transmission_type)
                control.set_period(period)
                control.set_search_timeout(12)
                control.set_rf_freq(ANTPLUS_RF_FREQUENCY)
                control.open()
                control.send_acknowledged_data(list(payload))
            finally:
                if control is not None:
                    try:
                        node.remove_channel(control)
                    except Exception:
                        _LOGGER.debug("Failed to remove ANT+ control channel", exc_info=True)
                if self._enabled and self._node is node:
                    scan.open_rx_scan_mode()

    def _run(self) -> None:
        try:
            if self.adapter.bus is None or self.adapter.address is None:
                raise RuntimeError(
                    f"USB bus/address unavailable for {self.adapter.stable_key}"
                )

            node = create_selected_node(
                self.adapter.pid,
                self.adapter.bus,
                self.adapter.address,
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
            channel.on_acknowledge_data = self._on_data
            channel.set_id(0, 0, 0)
            channel.enable_extended_messages(1)
            channel.set_rf_freq(ANTPLUS_RF_FREQUENCY)
            channel.open_rx_scan_mode()
            self._scan_channel = channel

            _LOGGER.info(
                "Capture started on local ANT USB adapter %s",
                self.adapter.stable_key,
            )
            self.state_callback(True, None)
            node.start()
        except Exception as err:
            _LOGGER.exception(
                "Capture failed on local ANT USB adapter %s",
                self.adapter.stable_key,
            )
            self.state_callback(False, str(err))
        finally:
            self._scan_channel = None
            self._node = None
            self.state_callback(False, None)
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
        self._remote_gateway_control_protocol: dict[str, int] = {}
        self._remote_control_waiters: dict[str, asyncio.Future] = {}
        self._local_scanners: dict[str, LocalAdapterScanner] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._capture_store = Store[dict[str, Any]](
            hass,
            CAPTURE_STORAGE_VERSION,
            CAPTURE_STORAGE_KEY,
            private=True,
            atomic_writes=True,
        )
        self._stored_capture_states: dict[str, bool] = {}

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
        """Persist only physical adapter identity, never live Capture state."""
        known = self._known_adapters()
        stored = record.adapter.identity_storage()

        existing = known.get(record.adapter.stable_key)
        if isinstance(existing, dict):
            existing_identity = {
                key: value
                for key, value in existing.items()
                if key != "capture_enabled"
            }
            if existing_identity == stored:
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
            desired = (
                bool(saved_capture)
                if saved_capture is not None
                else self._stored_capture_states.get(adapter.stable_key, False)
            )
            record = AdapterPresence(
                adapter=adapter,
                desired_capture=desired,
            )
            self._records[adapter.stable_key] = record
        else:
            record.adapter = adapter

        self._merge_or_register_device(adapter)
        self._persist_record(record)
        return record

    async def async_start(self) -> None:
        stored = await self._capture_store.async_load()
        if isinstance(stored, dict):
            states = stored.get("states")
            if isinstance(states, dict):
                self._stored_capture_states = {
                    str(key): bool(value)
                    for key, value in states.items()
                }

        # Migrate Capture state written by older integration versions.
        #
        # Capture state used to live as "capture_enabled" inside each
        # known_adapters record. New versions intentionally store live/user
        # Capture preferences separately in antplus.capture_states so changing
        # the switch does not update/reload the config entry.
        #
        # Existing Store values always win. The legacy value is only used when
        # this physical adapter has never yet been written to the new Store.
        migrated_capture_state = False

        for stable_key, data in self._known_adapters().items():
            if (
                stable_key not in self._stored_capture_states
                and "capture_enabled" in data
            ):
                self._stored_capture_states[stable_key] = bool(
                    data["capture_enabled"]
                )
                migrated_capture_state = True
                _LOGGER.info(
                    "Migrated persisted Capture state for ANT USB adapter %s: %s",
                    stable_key,
                    "ON" if self._stored_capture_states[stable_key] else "OFF",
                )

        if migrated_capture_state:
            await self._async_save_capture_states()

        for data in self._known_adapters().values():
            try:
                adapter = AntUsbAdapter.from_mapping(data)
            except (KeyError, TypeError, ValueError):
                continue
            self._ensure_record(
                adapter,
                saved_capture=None,
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
        self.expire_pending_capture_commands()

    def expire_pending_capture_commands(self) -> None:
        """Drop optimistic UI state when physical confirmation never arrives."""
        now = time.monotonic()

        for stable_key, record in self._records.items():
            if (
                record.pending_capture is None
                or record.pending_capture_since is None
            ):
                continue

            if (
                now - record.pending_capture_since
                < CAPTURE_CONFIRM_TIMEOUT_SECONDS
            ):
                continue

            _LOGGER.warning(
                "Timed out waiting for Capture %s confirmation from ANT USB "
                "adapter %s; reverting switch to confirmed physical state %s",
                "ON" if record.pending_capture else "OFF",
                stable_key,
                "ON" if record.capture_enabled else "OFF",
            )

            record.pending_capture = None
            record.pending_capture_since = None
            self._notify(stable_key)

    def _confirm_capture_state(
        self,
        stable_key: str,
        enabled: bool,
    ) -> None:
        """Resolve a pending command from a physical-state report."""
        record = self._records.get(stable_key)
        if record is None or record.pending_capture is None:
            return

        requested = record.pending_capture

        # Any authoritative state report resolves the pending operation.
        # If it matches, the optimistic state simply becomes confirmed.
        # If it differs, the switch falls back to the physical state.
        record.pending_capture = None
        record.pending_capture_since = None

        _LOGGER.debug(
            "Capture confirmation for ANT USB adapter %s: "
            "requested=%s confirmed=%s",
            stable_key,
            requested,
            bool(enabled),
        )

    def _sync_local_capture(self, stable_key: str) -> None:
        record = self._records.get(stable_key)
        if record is None:
            return

        scanner = self._local_scanners.get(stable_key)

        if record.local_present and record.desired_capture:
            if scanner is None:
                scanner = LocalAdapterScanner(
                    record.adapter,
                    self.receiver,
                    lambda enabled, error, key=stable_key: (
                        self.hass.loop.call_soon_threadsafe(
                            self._set_local_capture_state,
                            key,
                            enabled,
                            error,
                        )
                    ),
                )
                self._local_scanners[stable_key] = scanner
            scanner.start()
            return

        if scanner is not None:
            scanner.stop()
            self._local_scanners.pop(stable_key, None)

    def _set_local_capture_state(
        self,
        stable_key: str,
        enabled: bool,
        error: str | None,
    ) -> None:
        record = self._records.get(stable_key)
        if record is None:
            return
        previous = record.local_capture_enabled
        had_pending = record.pending_capture is not None

        record.local_capture_enabled = bool(enabled)

        if error:
            record.capture_error = error
        elif enabled:
            record.capture_error = None

        self._confirm_capture_state(stable_key, bool(enabled))

        if previous != bool(enabled) or error or had_pending:
            self._notify(stable_key)

    def update_remote_capture_state(
        self,
        gateway_id: str,
        stable_key: str,
        enabled: bool,
        error: str | None = None,
    ) -> None:
        record = self._records.get(stable_key)
        if record is None:
            return
        if gateway_id not in (record.remote_gateways or {}):
            return
        previous = record.remote_capture_states.get(gateway_id, False)
        had_pending = record.pending_capture is not None

        record.remote_capture_states[gateway_id] = bool(enabled)

        if error:
            record.capture_error = error
        elif enabled:
            record.capture_error = None

        self._confirm_capture_state(stable_key, bool(enabled))

        if previous != bool(enabled) or error or had_pending:
            self._notify(stable_key)

    async def _async_save_capture_states(self) -> None:
        await self._capture_store.async_save(
            {"states": dict(self._stored_capture_states)}
        )

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

        requested = bool(enabled)

        # Persist what HA wants across restarts.
        record.desired_capture = requested
        self._stored_capture_states[stable_key] = requested
        await self._async_save_capture_states()

        # Optimistically expose the requested state while waiting for the
        # actual physical adapter to confirm it.
        record.pending_capture = requested
        record.pending_capture_since = time.monotonic()
        record.capture_error = None

        # Notify before dispatch so the switch moves immediately.
        self._notify(stable_key)

        self._sync_local_capture(stable_key)

        for gateway_id in sorted(record.remote_gateways or {}):
            self._send_remote_capture(
                stable_key,
                gateway_id,
                requested,
            )

    def _device_sources(self, device_id: int) -> list[str]:
        device = self.receiver.devices.get(device_id)
        if device is None:
            return []
        return sorted(device.decoder_state.get("sources", set()))

    def can_control_device(self, device_id: int) -> bool:
        for source in self._device_sources(device_id):
            if source.startswith("local:"):
                key = source.split(":", 1)[1]
                scanner = self._local_scanners.get(key)
                if scanner is not None and scanner.running:
                    return True
            elif source.startswith("remote:"):
                parts = source.split(":", 2)
                if len(parts) == 3:
                    gateway_id, adapter_id = parts[1], parts[2]
                    record = self._records.get(adapter_id)
                    if (
                        record
                        and gateway_id in (record.remote_gateways or {})
                        and record.remote_capture_states.get(gateway_id, False)
                        and self._remote_gateway_control_protocol.get(gateway_id, 0) >= REMOTE_CONTROL_PROTOCOL
                    ):
                        return True
        return False

    async def async_send_control(
        self,
        *,
        device_id: int,
        device_type: int,
        payload: bytes,
        period: int,
        transmission_type: int | None = None,
    ) -> None:
        device = self.receiver.devices.get(device_id)
        if device is None:
            raise RuntimeError(f"ANT+ device {device_id} is not known")
        if len(payload) != 8:
            raise ValueError("ANT+ control payload must be exactly 8 bytes")
        profile_tx = device.decoder_state.get("profile_transmission_types", {}).get(device_type, set())
        if transmission_type is None:
            transmission_type = min(profile_tx) if profile_tx else (min(device.transmission_types) if device.transmission_types else 0)
        transmission_type = int(transmission_type) & 0xFF

        # Prefer a local adapter that has actually heard this ANT device.
        for source in self._device_sources(device_id):
            if not source.startswith("local:"):
                continue
            key = source.split(":", 1)[1]
            scanner = self._local_scanners.get(key)
            if scanner is None or not scanner.running:
                continue
            await self.hass.async_add_executor_job(
                lambda scanner=scanner: scanner.send_acknowledged(
                    device_id=device_id,
                    device_type=device_type,
                    transmission_type=transmission_type,
                    payload=payload,
                    period=period,
                )
            )
            return

        # Otherwise route to a gateway/adapter that saw the device.
        for source in self._device_sources(device_id):
            if not source.startswith("remote:"):
                continue
            parts = source.split(":", 2)
            if len(parts) != 3:
                continue
            gateway_id, adapter_id = parts[1], parts[2]
            record = self._records.get(adapter_id)
            if not record or gateway_id not in (record.remote_gateways or {}):
                continue
            if not record.remote_capture_states.get(gateway_id, False):
                continue
            if self._remote_gateway_control_protocol.get(gateway_id, 0) < REMOTE_CONTROL_PROTOCOL:
                continue

            command_id = uuid.uuid4().hex
            future = self.hass.loop.create_future()
            self._remote_control_waiters[command_id] = future
            self.hass.bus.async_fire(
                REMOTE_ADAPTER_CONTROL_EVENT,
                {
                    "gateway_id": gateway_id,
                    "adapter_id": adapter_id,
                    "command_id": command_id,
                    "device_id": device_id,
                    "device_type": device_type,
                    "transmission_type": transmission_type,
                    "period": period,
                    "payload": payload.hex(),
                },
            )
            try:
                result = await asyncio.wait_for(future, timeout=REMOTE_CONTROL_TIMEOUT)
            except asyncio.TimeoutError as err:
                raise RuntimeError(
                    f"Remote ANT+ gateway {gateway_id} did not confirm control command"
                ) from err
            finally:
                self._remote_control_waiters.pop(command_id, None)

            if not bool(result.get("success", False)):
                detail = str(result.get("error") or "remote gateway rejected command")
                raise RuntimeError(detail)
            return

        raise RuntimeError(
            f"No active ANT adapter that has seen device {device_id} is available for control"
        )

    def resolve_remote_control_result(self, data: dict[str, Any]) -> None:
        """Resolve one correlated remote-gateway control command."""
        command_id = str(data.get("command_id", "")).strip()
        if not command_id:
            return
        future = self._remote_control_waiters.get(command_id)
        if future is None or future.done():
            return
        future.set_result(dict(data))

    async def async_refresh_local(self) -> None:
        adapters = await self.hass.async_add_executor_job(
            scan_linux_ant_adapters
        )
        present_keys = {adapter.stable_key for adapter in adapters}

        now = time.monotonic()

        for adapter in adapters:
            record = self._ensure_record(adapter)
            changed = not record.local_present
            record.local_present = True
            record.local_missing_since = None
            self._sync_local_capture(adapter.stable_key)
            if changed:
                self._notify(adapter.stable_key)

        for stable_key, record in self._records.items():
            if not record.local_present or stable_key in present_keys:
                continue

            if record.local_missing_since is None:
                record.local_missing_since = now
                continue

            if now - record.local_missing_since <= LOCAL_MISSING_GRACE_SECONDS:
                continue

            record.local_present = False
            record.local_missing_since = None
            record.local_capture_enabled = False
            self._sync_local_capture(stable_key)
            self._notify(stable_key)

    def update_remote_gateway(
        self,
        gateway_id: str,
        adapters: list[AntUsbAdapter],
        *,
        reconcile_capture: bool = False,
        control_protocol: int = 0,
    ) -> None:
        now = time.monotonic()
        self._remote_gateway_last_seen[gateway_id] = now
        self._remote_gateway_control_protocol[gateway_id] = max(0, int(control_protocol))
        current_keys = {adapter.stable_key for adapter in adapters}

        for stable_key, record in self._records.items():
            if gateway_id not in (record.remote_gateways or {}):
                continue

            if stable_key in current_keys:
                record.remote_missing_since.pop(gateway_id, None)
                continue

            record.remote_missing_since.setdefault(gateway_id, now)

        for adapter in adapters:
            adapter.source = "remote"
            adapter.gateway_id = gateway_id
            record = self._ensure_record(adapter)
            new_presence = gateway_id not in (record.remote_gateways or {})
            record.remote_gateways[gateway_id] = now
            record.remote_missing_since.pop(gateway_id, None)

            if new_presence or reconcile_capture:
                self._send_remote_capture(
                    adapter.stable_key,
                    gateway_id,
                    record.desired_capture,
                )
                self._notify(adapter.stable_key)

    def expire_remote_gateways(self) -> None:
        now = time.monotonic()

        expired_gateways = {
            gateway_id
            for gateway_id, last_seen in self._remote_gateway_last_seen.items()
            if now - last_seen > REMOTE_EXPIRE_SECONDS
        }

        for gateway_id in expired_gateways:
            self._remote_gateway_last_seen.pop(gateway_id, None)
            self._remote_gateway_control_protocol.pop(gateway_id, None)

        for stable_key, record in self._records.items():
            changed = False

            for gateway_id in expired_gateways:
                record.remote_missing_since.pop(gateway_id, None)
                record.remote_capture_states.pop(gateway_id, None)
                if gateway_id in (record.remote_gateways or {}):
                    record.remote_gateways.pop(gateway_id, None)
                    changed = True

            for gateway_id, missing_since in list(
                (record.remote_missing_since or {}).items()
            ):
                if gateway_id not in self._remote_gateway_last_seen:
                    record.remote_missing_since.pop(gateway_id, None)
                    continue

                if (
                    now - missing_since
                    > REMOTE_ADAPTER_MISSING_GRACE_SECONDS
                ):
                    record.remote_gateways.pop(gateway_id, None)
                    record.remote_missing_since.pop(gateway_id, None)
                    record.remote_capture_states.pop(gateway_id, None)
                    changed = True

            if changed:
                self._notify(stable_key)
