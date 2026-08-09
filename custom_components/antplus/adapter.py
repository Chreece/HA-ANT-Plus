"""Physical ANT USB adapter identity, presence and registry management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import logging
from pathlib import Path
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORTED_USB_IDS = {
    ("0FCF", "1008"),
    ("0FCF", "1009"),
}

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
            self.serial = self.serial.strip() or None
        if self.manufacturer is not None:
            self.manufacturer = self.manufacturer.strip() or None
        if self.product is not None:
            self.product = self.product.strip() or None

    @property
    def stable_key(self) -> str:
        """Return a physical-device key which survives host changes."""
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

    def as_storage(self) -> dict[str, Any]:
        """Return identity metadata only; transport location is runtime state."""
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
    """Runtime presence for one physical adapter."""

    adapter: AntUsbAdapter
    local_present: bool = False
    remote_gateways: dict[str, float] | None = None

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
            gateways = ", ".join(sorted(self.remote_gateways))
            return f"Local + {gateways}"
        if self.local_present:
            return "Local"
        if self.remote_gateways:
            return ", ".join(sorted(self.remote_gateways))
        return "Unavailable"


def scan_linux_ant_adapters() -> list[AntUsbAdapter]:
    """Find all supported ANT USB adapters through Linux sysfs."""
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


class AntAdapterManager:
    """Track physical ANT USB adapters independently of transport location."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._records: dict[str, AdapterPresence] = {}
        self._callbacks: list[AdapterCallback] = []
        self._remote_gateway_last_seen: dict[str, float] = {}
        self._unsubs: list[Callable[[], None]] = []

    @property
    def records(self) -> dict[str, AdapterPresence]:
        return self._records

    def add_callback(self, callback: AdapterCallback) -> Callable[[], None]:
        self._callbacks.append(callback)

        def remove() -> None:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

        return remove

    def get(self, stable_key: str) -> AdapterPresence | None:
        return self._records.get(stable_key)

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

    def _persist_adapter(self, adapter: AntUsbAdapter) -> None:
        known = self._known_adapters()
        stored = adapter.as_storage()

        if known.get(adapter.stable_key) == stored:
            return

        known[adapter.stable_key] = stored
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, KNOWN_ADAPTERS_KEY: known},
        )

    def _merge_or_register_device(self, adapter: AntUsbAdapter) -> None:
        """Create the physical device or merge the old generic adapter into it."""
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
            _LOGGER.info(
                "Migrating legacy ANT+ USB adapter to physical identity %s",
                adapter.stable_key,
            )
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
        if (
            legacy is not None
            and physical is not None
            and legacy.id != physical.id
        ):
            _LOGGER.info(
                "Merging duplicate legacy ANT+ USB adapter %s into %s",
                legacy.id,
                physical.id,
            )

            for entity in list(entity_registry.entities.values()):
                if entity.device_id == legacy.id:
                    entity_registry.async_update_entity(
                        entity.entity_id,
                        device_id=physical.id,
                    )

            changes: dict[str, Any] = {}
            if physical.area_id is None and legacy.area_id is not None:
                changes["area_id"] = legacy.area_id

            legacy_name_by_user = getattr(legacy, "name_by_user", None)
            physical_name_by_user = getattr(physical, "name_by_user", None)
            if physical_name_by_user is None and legacy_name_by_user:
                changes["name_by_user"] = legacy_name_by_user

            if changes:
                device_registry.async_update_device(
                    physical.id,
                    **changes,
                )

            device_registry.async_remove_device(legacy.id)

    def _ensure_record(self, adapter: AntUsbAdapter) -> AdapterPresence:
        record = self._records.get(adapter.stable_key)

        if record is None:
            record = AdapterPresence(adapter=adapter)
            self._records[adapter.stable_key] = record
        else:
            record.adapter = adapter

        self._merge_or_register_device(adapter)
        self._persist_adapter(adapter)
        return record

    async def async_start(self) -> None:
        """Load remembered adapters and start local/remote presence maintenance."""
        for data in self._known_adapters().values():
            try:
                adapter = AntUsbAdapter.from_mapping(data)
            except (KeyError, TypeError, ValueError):
                continue
            self._ensure_record(adapter)

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
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _async_local_tick(self, _now) -> None:
        await self.async_refresh_local()

    async def _async_expire_tick(self, _now) -> None:
        self.expire_remote_gateways()

    async def async_refresh_local(self) -> None:
        """Refresh physical adapters attached to the Home Assistant host."""
        adapters = await self.hass.async_add_executor_job(
            scan_linux_ant_adapters
        )
        present_keys = {adapter.stable_key for adapter in adapters}

        for adapter in adapters:
            record = self._ensure_record(adapter)
            changed = not record.local_present
            record.local_present = True
            if changed:
                _LOGGER.info(
                    "ANT+ USB adapter %s is available locally",
                    adapter.stable_key,
                )
                self._notify(adapter.stable_key)

        for stable_key, record in self._records.items():
            if record.local_present and stable_key not in present_keys:
                record.local_present = False
                _LOGGER.info(
                    "ANT+ USB adapter %s is no longer available locally",
                    stable_key,
                )
                self._notify(stable_key)

    def update_remote_gateway(
        self,
        gateway_id: str,
        adapters: list[AntUsbAdapter],
    ) -> None:
        """Apply one complete heartbeat/status snapshot from a gateway."""
        now = time.monotonic()
        self._remote_gateway_last_seen[gateway_id] = now

        current_keys = {adapter.stable_key for adapter in adapters}

        for stable_key, record in self._records.items():
            if (
                gateway_id in (record.remote_gateways or {})
                and stable_key not in current_keys
            ):
                record.remote_gateways.pop(gateway_id, None)
                _LOGGER.info(
                    "ANT+ USB adapter %s disappeared from gateway %s",
                    stable_key,
                    gateway_id,
                )
                self._notify(stable_key)

        for adapter in adapters:
            adapter.source = "remote"
            adapter.gateway_id = gateway_id
            record = self._ensure_record(adapter)
            was_present = gateway_id in (record.remote_gateways or {})
            record.remote_gateways[gateway_id] = now

            if not was_present:
                _LOGGER.info(
                    "ANT+ USB adapter %s is available via gateway %s",
                    adapter.stable_key,
                    gateway_id,
                )
                self._notify(adapter.stable_key)

    def expire_remote_gateways(self) -> None:
        """Expire gateways which stopped heartbeating."""
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
                _LOGGER.info(
                    "ANT+ USB adapter %s became unavailable via expired gateway",
                    stable_key,
                )
                self._notify(stable_key)
