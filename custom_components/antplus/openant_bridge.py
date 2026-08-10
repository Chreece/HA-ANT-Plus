"""Bridge OpenANT's shipped ANT+ profile parsers into our scan-mode receiver.

The actual radio traffic is received by one wildcard continuous RX scan
channel. These objects are parser-only instances: they never touch USB or
allocate ANT hardware channels.
"""

from __future__ import annotations
from homeassistant.helpers.entity import EntityCategory

import array
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any

from .models import AntMetric

_LOGGER = logging.getLogger(__name__)


class _FakeChannel:
    """No-op ANT channel used only to initialise OpenANT parser classes."""

    id = 0

    def __getattr__(self, _name):
        def noop(*_args, **_kwargs):
            return None
        return noop


class _FakeNode:
    """No-op node used only to initialise OpenANT parser classes."""

    def new_channel(self, *_args, **_kwargs):
        return _FakeChannel()

    def __getattr__(self, _name):
        def noop(*_args, **_kwargs):
            return None
        return noop


# Import lazily/defensively: one broken optional profile must never prevent
# the whole integration from loading.
def _profile_classes() -> dict[int, type]:
    classes: dict[int, type] = {}

    candidates = (
        (11, "openant.devices.power_meter", "PowerMeter"),
        (16, "openant.devices.controls_device", "ControlsDevice"),
        (17, "openant.devices.fitness_equipment", "FitnessEquipment"),
        (20, "openant.devices.lev", "Lev"),
        (25, "openant.devices.environment", "Environment"),
        (34, "openant.devices.shift", "Shifting"),
        (48, "openant.devices.tire_pressure_monitor", "TirePressureMonitor"),
        (115, "openant.devices.dropper_seatpost", "DropperSeatpost"),
        (120, "openant.devices.heart_rate", "HeartRate"),
        (121, "openant.devices.bike_speed_cadence", "BikeSpeedCadence"),
        (122, "openant.devices.bike_speed_cadence", "BikeCadence"),
        (123, "openant.devices.bike_speed_cadence", "BikeSpeed"),
        (127, "openant.devices.core_temp", "CoreTemp"),

        # Additional published ANT+ profiles. Imports are deliberately
        # defensive: supported OpenANT versions gain semantic decoding
        # automatically; otherwise raw/common-page fallback remains active.
    )

    import importlib

    for device_type, module_name, class_name in candidates:
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
        except (ModuleNotFoundError, AttributeError):
            _LOGGER.debug(
                "OpenANT optional parser %s.%s unavailable",
                module_name,
                class_name,
            )
            continue
        except Exception:
            _LOGGER.exception(
                "Unexpected error loading OpenANT parser %s.%s",
                module_name,
                class_name,
            )
            continue
        classes[device_type] = cls

    return classes


PROFILE_CLASSES = _profile_classes()


def supported_profile_types() -> set[int]:
    """Return profile device types backed by OpenANT parser classes."""
    return set(PROFILE_CLASSES)


class OpenAntParserAdapter:
    """Parser-only wrapper around one OpenANT device profile object."""

    def __init__(self, device_type: int, device_id: int) -> None:
        cls = PROFILE_CLASSES[device_type]
        self.device_type = device_type
        self.device_id = device_id
        self._captured: list[tuple[str, Any]] = []

        parser = cls(
            _FakeNode(),
            device_id=device_id,
            trans_type=0,
        )

        # Profile parsers call this when a decoded datapage has changed.
        parser.on_device_data = self._on_device_data

        # Several profiles expose battery through this callback.
        try:
            parser.on_battery = self._on_battery
        except Exception:
            pass

        self.parser = parser

    def _on_device_data(self, _page: int, page_name: str, data: Any) -> None:
        self._captured.append((page_name, data))

    def _on_battery(self, data: Any) -> None:
        self._captured.append(("battery", data))

    def feed(self, payload: bytes) -> list[AntMetric]:
        """Feed one 8-byte profile packet into the upstream parser."""
        self._captured.clear()

        try:
            # Profile-specific parser. Common pages are decoded separately
            # by our integration to avoid vendor/proprietary page collisions.
            self.parser.on_data(array.array("B", payload))
        except Exception:
            _LOGGER.debug(
                "OpenANT parser failed for device %s type %s payload %s",
                self.device_id,
                self.device_type,
                payload.hex(" "),
                exc_info=True,
            )
            return []

        metrics: list[AntMetric] = []
        for page_name, data in self._captured:
            metrics.extend(_dataclass_to_metrics(page_name, data))
        return metrics



def _dataclass_to_metrics(page_name: str, data: Any) -> list[AntMetric]:
    """Convert every useful OpenANT dataclass field into HA state.

    Primary measurements stay normal entities. Protocol bookkeeping and
    identification values remain available as diagnostic entities instead of
    being silently suppressed. Complex values are normalized to stable text.
    """
    if not is_dataclass(data):
        return []

    now = datetime.now(timezone.utc)
    out: list[AntMetric] = []
    values: dict[str, Any] = {}
    for field in fields(data):
        try:
            values[field.name] = getattr(data, field.name)
        except Exception:
            continue

    is_battery_page = page_name == "battery"
    if is_battery_page and ("voltage_coarse" in values or "voltage_fractional" in values):
        coarse = values.get("voltage_coarse")
        fractional = values.get("voltage_fractional")
        if isinstance(coarse, (int, float)) and coarse not in (-1, 15, 255):
            voltage = float(coarse) + float(fractional or 0)
            if voltage > 0:
                out.append(AntMetric(key="battery_voltage", name="Battery Voltage", value=round(voltage,3), unit="V", device_class="voltage", state_class="measurement", icon="mdi:battery", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=True, updated_at=now, availability_mode="device"))
        percentage = values.get("battery_percentage")
        if isinstance(percentage,(int,float)) and 0 <= percentage <= 100:
            out.append(AntMetric(key="battery_level", name="Battery", value=percentage, unit="%", device_class="battery", state_class="measurement", icon="mdi:battery", entity_category=EntityCategory.DIAGNOSTIC, enabled_default=True, updated_at=now, availability_mode="device"))

    diagnostic_fields = {
        "page_specific", "manufacturer_id_lsb", "manufacturer_id", "serial_number",
        "serial_no", "hardware_rev", "hardware_revision", "software_rev",
        "software_revision", "model_no", "model_number", "voltage_coarse",
        "voltage_fractional", "battery_percentage", "beat_count", "beat_time",
        "previous_heart_beat_time", "operating_time", "event_count",
        "accumulated_power", "accumulated_torque", "crank_ticks", "wheel_ticks",
        "command_sequence", "slave_serial", "slave_manufacturer_id",
        "last_received_command_page", "response_data", "capabilities",
    }

    for field in fields(data):
        name = field.name
        try:
            value = getattr(data, name)
        except Exception:
            continue
        if value is None:
            continue
        if isinstance(value, Enum):
            value = value.name
        elif isinstance(value, set):
            value = ", ".join(sorted(getattr(v, "name", str(v)) for v in value))
        elif isinstance(value, (list, tuple)):
            value = ", ".join(getattr(v, "name", str(v)) for v in value)
        elif isinstance(value, dict):
            value = ", ".join(f"{k}={v}" for k,v in sorted(value.items(), key=lambda item: str(item[0])))
        elif is_dataclass(value):
            continue
        if isinstance(value, int) and value in {-1,0xFF,0xFFFF,0xFFFFFF,0xFFFFFFFF}:
            continue
        if isinstance(value,float) and value != value:
            continue

        unit = field.metadata.get("unit") if field.metadata else None
        key = _normalise_key(name)
        friendly = name.replace("_"," ").title()
        device_class,state_class,icon = _ha_semantics(key,unit)
        diagnostic = name in diagnostic_fields or is_battery_page
        out.append(AntMetric(key=key,name=friendly,value=value,unit=unit,device_class=device_class,state_class=state_class,icon=icon,entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,enabled_default=not diagnostic or name in {"status"},updated_at=now,availability_mode="device" if diagnostic else "metric"))
    return out

def _normalise_key(name: str) -> str:
    aliases = {
        "instantaneous_power": "power",
        "average_power": "average_power",
        "heart_rate": "heart_rate",
        "temperature": "temperature",
        "core_temperature": "core_temperature",
        "battery_percentage": "battery_level",
    }
    return aliases.get(name, name)


def _ha_semantics(key: str, unit: str | None):
    key_l = key.lower()
    unit_l = (unit or "").lower()

    if "heart_rate" in key_l:
        return "heart_rate", "measurement", "mdi:heart-pulse"
    if "power" in key_l and unit_l in {"watts", "w"}:
        return "power", "measurement", "mdi:flash"
    if "temperature" in key_l:
        return "temperature", "measurement", "mdi:thermometer"
    if "pressure" in key_l:
        return "pressure", "measurement", "mdi:gauge"
    if "voltage" in key_l:
        return "voltage", "measurement", "mdi:battery"
    if "battery" in key_l and ("percent" in unit_l or unit_l == "%"):
        return "battery", "measurement", "mdi:battery"
    if "speed" in key_l:
        return "speed", "measurement", "mdi:speedometer"
    if "distance" in key_l:
        return "distance", "total_increasing", "mdi:map-marker-distance"
    if "cadence" in key_l:
        return None, "measurement", "mdi:rotate-right"
    if "torque" in key_l:
        return None, "measurement", "mdi:rotate-orbit"

    return None, "measurement" if isinstance(unit, str) and unit else None, None
