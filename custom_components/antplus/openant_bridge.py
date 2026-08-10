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

# OpenANT logs every power packet at INFO. Under high-rate sensors this can
# flood HA logs and add avoidable MainThread I/O; keep warnings/errors only.
logging.getLogger("openant.devices.power_meter").setLevel(logging.WARNING)


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
    """Convert useful OpenANT dataclass fields into canonical HA metrics.

    Native and OpenANT parse the same packet stream, so OpenANT field names are
    normalized to the integration's canonical metric keys before the two
    backends are merged. Raw byte/component fields that contain no information
    beyond an already exposed composite value remain available through the
    per-profile Raw Data diagnostic instead of becoming duplicate entities.
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

    # OpenANT also names some profile-specific pages "battery" (for example
    # LEV page 0x04). Identify the ANT Common BatteryData callback by its
    # component fields instead of the page-name string alone.
    is_battery_page = (
        page_name == "battery"
        and "battery_id" in values
        and "voltage_coarse" in values
        and "voltage_fractional" in values
    )

    # Component-only fields are useful to a protocol debugger, but exposing
    # them independently duplicates the canonical value. The bounded Raw Data
    # entity already preserves the original bytes losslessly.
    suppressed_components = {
        "page_specific",
        "voltage_coarse",
        "voltage_fractional",
    }

    # Common Page 82 battery fields need battery-specific names. Without this,
    # a profile's own operating_time/status can collide with battery state.
    battery_aliases = {
        "status": "battery_status",
        "operating_time": "battery_operating_time",
        "battery_id": "battery_id",
    }

    # OpenANT's HeartRateData names are different from our native decoder even
    # though they represent the exact same ANT fields. Normalize them so native
    # decoding wins instead of creating duplicate HA entities.
    profile_fragment_aliases = {
        "manufacturer_id_lsb": "manufacturer_id",
        "serial_number": "device_serial_fragment",
    }
    heart_rate_aliases = {
        "beat_count": "heart_beat_count",
        "beat_time": "heart_beat_time",
        "battery_percentage": "battery_level",
        **profile_fragment_aliases,
    }

    general_aliases = {
        "instantaneous_power": "power",
        "instantaneous_speed": "speed",
        "instantaneous_cadence": "cadence",
        "battery_percentage": "battery_level",
        "battery_soc": "battery_level",
        "cumulative_operating_time": "operating_time",
        "hardware_rev": "hardware_revision",
        "software_rev": "software_revision",
        "software_ver": "software_revision",
        "model_no": "model_number",
        "serial_no": "serial_number",
    }

    diagnostic_keys = {
        "manufacturer_id",
        "device_serial_fragment",
        "serial_number",
        "hardware_revision",
        "software_revision",
        "model_number",
        "battery_id",
        "battery_operating_time",
        "heart_beat_count",
        "heart_beat_time",
        "previous_heart_beat_time",
        "operating_time",
        "event_count",
        "accumulated_power",
        "accumulated_torque",
        "crank_ticks",
        "wheel_ticks",
        "command_sequence",
        "slave_serial",
        "slave_manufacturer_id",
        "last_received_command_page",
        "response_data",
        "capabilities",
    }

    useful_diagnostics_enabled = {
        "battery_status",
        "battery_voltage",
    }

    # Synthesize canonical battery voltage before suppressing its component
    # fields. Native decoding will take precedence when both backends know it.
    if is_battery_page and (
        "voltage_coarse" in values or "voltage_fractional" in values
    ):
        coarse = values.get("voltage_coarse")
        fractional = values.get("voltage_fractional")
        if isinstance(coarse, (int, float)) and coarse not in (-1, 15, 255):
            voltage = float(coarse) + float(fractional or 0)
            if voltage > 0:
                out.append(
                    AntMetric(
                        key="battery_voltage",
                        name="Battery Voltage",
                        value=round(voltage, 3),
                        unit="V",
                        device_class="voltage",
                        state_class="measurement",
                        icon="mdi:battery",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        enabled_default=True,
                        updated_at=now,
                        availability_mode="device",
                    )
                )

    for field in fields(data):
        name = field.name
        if name in suppressed_components:
            continue

        try:
            value = getattr(data, name)
        except Exception:
            continue
        if value is None:
            continue
        complex_value = isinstance(value, (set, list, tuple, dict))
        if isinstance(value, Enum):
            value = value.name
        elif isinstance(value, set):
            value = ", ".join(
                sorted(getattr(v, "name", str(v)) for v in value)
            )
        elif isinstance(value, (list, tuple)):
            value = ", ".join(getattr(v, "name", str(v)) for v in value)
        elif isinstance(value, dict):
            value = ", ".join(
                f"{k}={v}"
                for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            )
        elif is_dataclass(value):
            continue

        if isinstance(value, int) and value in {
            -1,
            0xFF,
            0xFFFF,
            0xFFFFFF,
            0xFFFFFFFF,
        }:
            continue
        if isinstance(value, float) and value != value:
            continue

        if is_battery_page:
            key = battery_aliases.get(name, general_aliases.get(name, name))
        elif page_name == "heart_rate":
            key = heart_rate_aliases.get(name, general_aliases.get(name, name))
        elif page_name in {"bike_speed", "bike_cadence"}:
            key = profile_fragment_aliases.get(
                name, general_aliases.get(name, name)
            )
        else:
            key = general_aliases.get(name, name)

        # A bare "status" key is ambiguous across profiles. Namespace it by
        # the OpenANT page name so two status-bearing profiles can coexist.
        if key == "status":
            page_key = _normalise_page_name(page_name)
            key = f"{page_key}_status"

        # The HR page-specific value is already covered by Raw Data and has no
        # stable semantic meaning across rotating HR pages.
        if (
            page_name in {"heart_rate", "bike_speed", "bike_cadence"}
            and name == "manufacturer_id_lsb"
        ):
            friendly = "Manufacturer ID"
        elif (
            page_name in {"heart_rate", "bike_speed", "bike_cadence"}
            and name == "serial_number"
        ):
            friendly = "Device Serial Fragment"
        else:
            friendly = _friendly_name(key)

        unit = field.metadata.get("unit") if field.metadata else None
        if key in {"battery_operating_time", "operating_time"} and unit in {None, "seconds"}:
            unit = "s"
        if key == "battery_level" and unit is None:
            unit = "%"
        device_class, state_class, icon = _ha_semantics(key, unit)

        is_status = key.endswith("_status")
        diagnostic = (
            is_battery_page
            or key in diagnostic_keys
            or is_status
            or complex_value
            or key.startswith("supported_")
            or key.endswith("_event_time")
            or key.startswith("cumulative_")
        )
        enabled_default = (
            not diagnostic
            or key in useful_diagnostics_enabled
            or is_status
        )

        out.append(
            AntMetric(
                key=key,
                name=friendly,
                value=value,
                unit=unit,
                device_class=device_class,
                state_class=state_class,
                icon=icon,
                entity_category=(
                    EntityCategory.DIAGNOSTIC if diagnostic else None
                ),
                enabled_default=enabled_default,
                updated_at=now,
                availability_mode="device" if diagnostic else "metric",
            )
        )

    return _deduplicate_metrics(out)


def _normalise_page_name(page_name: str) -> str:
    """Return a stable entity-key fragment for an OpenANT page name."""
    normalized = "".join(
        ch.lower() if ch.isalnum() else "_" for ch in page_name.strip()
    )
    return "_".join(part for part in normalized.split("_") if part) or "profile"


def _friendly_name(key: str) -> str:
    """Turn a canonical metric key into a stable HA display name."""
    canonical = {
        "battery_level": "Battery",
        "power": "Power",
        "heart_rate": "Heart Rate",
        "cadence": "Cadence",
        "speed": "Speed",
    }
    if key in canonical:
        return canonical[key]
    acronyms = {"id": "ID", "ids": "IDs", "lev": "LEV", "tpms": "TPMS"}
    return " ".join(
        acronyms.get(part, part.capitalize())
        for part in key.split("_")
    )


def _deduplicate_metrics(metrics: list[AntMetric]) -> list[AntMetric]:
    """Keep the first canonical metric when one OpenANT page repeats a field."""
    deduplicated: dict[str, AntMetric] = {}
    for metric in metrics:
        deduplicated.setdefault(metric.key, metric)
    return list(deduplicated.values())


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
    if key_l.endswith("operating_time"):
        return "duration", "total_increasing", "mdi:timer-outline"

    return None, "measurement" if isinstance(unit, str) and unit else None, None
