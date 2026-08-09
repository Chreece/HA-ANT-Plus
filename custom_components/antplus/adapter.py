"""Physical ANT USB adapter identity and Home Assistant device registration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORTED_USB_IDS = {
    ("0FCF", "1008"),
    ("0FCF", "1009"),
}

KNOWN_ADAPTERS_KEY = "known_adapters"
LEGACY_ADAPTER_IDENTIFIER = (DOMAIN, "usb_adapter")


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
        """Return a physical-device key.

        Serial-numbered adapters retain identity when moved between hosts.
        For hardware without a serial number we fall back to a fingerprint;
        that fallback cannot guarantee cross-host physical identity.
        """
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
        data = asdict(self)
        data["stable_key"] = self.stable_key
        return data

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


def scan_linux_ant_adapters() -> list[AntUsbAdapter]:
    """Find supported ANT USB adapters through Linux sysfs."""
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


def _known_adapters(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    raw = entry.data.get(KNOWN_ADAPTERS_KEY, {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if isinstance(value, dict)
    }


def _persist_adapter(
    hass: HomeAssistant,
    entry: ConfigEntry,
    adapter: AntUsbAdapter,
) -> None:
    known = _known_adapters(entry)
    stored = adapter.as_storage()

    # Runtime location may change; identity does not.
    previous = known.get(adapter.stable_key)
    if previous == stored:
        return

    known[adapter.stable_key] = stored
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, KNOWN_ADAPTERS_KEY: known},
    )


def _register_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    adapter: AntUsbAdapter,
    *,
    allow_legacy_migration: bool,
) -> None:
    registry = dr.async_get(hass)
    identifier = adapter.ha_identifier

    existing = registry.async_get_device_by_identifier(
        identifier,
        entry.entry_id,
    )

    if existing is None and allow_legacy_migration:
        legacy = registry.async_get_device_by_identifier(
            LEGACY_ADAPTER_IDENTIFIER,
            entry.entry_id,
        )
        if legacy is not None:
            _LOGGER.info(
                "Migrating legacy ANT+ USB adapter device to physical identity %s",
                adapter.stable_key,
            )
            registry.async_update_device(
                legacy.id,
                new_identifiers={identifier},
                name=adapter.name,
                manufacturer=adapter.manufacturer or "Dynastream / Garmin",
                model=adapter.product or f"ANT USB {adapter.vid}:{adapter.pid}",
                serial_number=adapter.serial,
            )
            return

    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={identifier},
        name=adapter.name,
        manufacturer=adapter.manufacturer or "Dynastream / Garmin",
        model=adapter.product or f"ANT USB {adapter.vid}:{adapter.pid}",
        serial_number=adapter.serial,
    )


def async_register_adapter(
    hass: HomeAssistant,
    entry: ConfigEntry,
    adapter: AntUsbAdapter,
    *,
    allow_legacy_migration: bool = False,
) -> None:
    """Register/update one physical ANT USB adapter."""
    _register_device(
        hass,
        entry,
        adapter,
        allow_legacy_migration=allow_legacy_migration,
    )
    _persist_adapter(hass, entry, adapter)


def async_register_known_adapters(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Re-register remembered physical adapters even while offline."""
    known = _known_adapters(entry)

    for data in known.values():
        try:
            adapter = AntUsbAdapter.from_mapping(data)
        except (KeyError, TypeError, ValueError):
            continue

        _register_device(
            hass,
            entry,
            adapter,
            allow_legacy_migration=False,
        )


async def async_scan_local_adapters(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> list[AntUsbAdapter]:
    """Discover and register adapters physically attached to the HA host."""
    adapters = await hass.async_add_executor_job(scan_linux_ant_adapters)

    # The legacy integration represented one adapter as ("antplus", "usb_adapter").
    # If exactly one physical adapter is present, migrate that old HA device instead
    # of creating a duplicate.
    migrate_legacy = len(adapters) == 1

    for adapter in adapters:
        async_register_adapter(
            hass,
            entry,
            adapter,
            allow_legacy_migration=migrate_legacy,
        )
        migrate_legacy = False

    return adapters
