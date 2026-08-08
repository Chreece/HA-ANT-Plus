"""Runtime models for ANT+."""

from __future__ import annotations
from homeassistant.helpers.entity import EntityCategory

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class AntMetric:
    """A decoded ANT+ metric."""

    key: str
    name: str
    value: Any
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    entity_category: EntityCategory | None = None
    enabled_default: bool = True
    updated_at: datetime | None = None
    availability_mode: str = "metric"  # metric | device


@dataclass(slots=True)
class AntDevice:
    """One physical ANT+ device, keyed by ANT device number."""

    device_id: int
    profiles: set[int] = field(default_factory=set)
    transmission_types: set[int] = field(default_factory=set)
    manufacturer_id: int | None = None
    manufacturer_name: str | None = None
    model_no: int | None = None
    hardware_rev: int | None = None
    serial_no: int | None = None
    software_ver: str | None = None
    last_seen: datetime | None = None
    metrics: dict[str, AntMetric] = field(default_factory=dict)
    decoder_state: dict[str, Any] = field(default_factory=dict)
