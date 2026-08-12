"""Central ANT+ runtime capability model.

Home Assistant control entities and semantic events must be derived from this
module rather than from a device-type check scattered across platforms.

Evidence order is intentionally conservative:
* explicit ANT+ capability flags / observed capability pages;
* observed profile pages that positively demonstrate a feature;
* profile-role guarantees where ANT+ does not expose a feature bitmap;
* explicit command-status feedback can revoke/confirm a capability.

No vendor, model or product-name exceptions belong here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import (
    DEVICE_TYPE_BIKE_CADENCE,
    DEVICE_TYPE_BIKE_SPEED,
    DEVICE_TYPE_BIKE_SPEED_CADENCE,
    DEVICE_TYPE_CONTROLS,
    DEVICE_TYPE_DROPPER,
    DEVICE_TYPE_FITNESS_EQUIPMENT,
    DEVICE_TYPE_LEV,
    DEVICE_TYPE_MULTI_SPORT_SPEED_DISTANCE,
    DEVICE_TYPE_POWER,
    DEVICE_TYPE_RUNNING_DYNAMICS,
    DEVICE_TYPE_SHIFTING,
    DEVICE_TYPE_STRIDE_SPEED,
    DEVICE_TYPE_TIRE_PRESSURE,
)
from .models import AntDevice

# Control capability IDs. These are internal stable semantic identifiers, not
# ANT page numbers, and are shared by button/number/select/service surfaces.
CONTROL_GENERIC = "generic_control"
CONTROL_FE_REQUEST_CAPABILITIES = "fe_request_capabilities"
CONTROL_FE_BASIC_RESISTANCE = "fe_basic_resistance"
CONTROL_FE_TARGET_POWER = "fe_target_power"
CONTROL_FE_SIMULATION = "fe_simulation"
CONTROL_FE_USER_CONFIGURATION = "fe_user_configuration"
CONTROL_FE_ZERO_OFFSET_CALIBRATION = "fe_zero_offset_calibration"
CONTROL_FE_SPINDOWN_CALIBRATION = "fe_spindown_calibration"
CONTROL_POWER_CALIBRATION = "power_calibration"
CONTROL_LEV = "lev_control"
CONTROL_DROPPER = "dropper_control"
CONTROL_TPMS_CONFIGURATION = "tpms_configuration"

# Event capability IDs.
EVENT_GENERIC_CONTROL = "generic_control_event"
EVENT_CONTROLS_AVAILABILITY = "controls_availability_event"
EVENT_FE_CALIBRATION = "fe_calibration_event"
EVENT_FE_COMMAND_STATUS = "fe_command_status_event"
EVENT_POWER_CALIBRATION = "power_calibration_event"
EVENT_SHIFT = "shift_event"
EVENT_DROPPER = "dropper_event"

_RUNNING_POWER_COMPANION_PROFILES = frozenset(
    {
        DEVICE_TYPE_MULTI_SPORT_SPEED_DISTANCE,
        DEVICE_TYPE_RUNNING_DYNAMICS,
        DEVICE_TYPE_STRIDE_SPEED,
    }
)
_CYCLING_COMPANION_PROFILES = frozenset(
    {
        DEVICE_TYPE_BIKE_SPEED_CADENCE,
        DEVICE_TYPE_BIKE_CADENCE,
        DEVICE_TYPE_BIKE_SPEED,
    }
)

# FE-C command-status page reports the requested command/page ID. Map the
# control pages we currently implement to their semantic capability.
_FE_COMMAND_CAPABILITY = {
    0x01: (CONTROL_FE_ZERO_OFFSET_CALIBRATION, CONTROL_FE_SPINDOWN_CALIBRATION),
    0x30: (CONTROL_FE_BASIC_RESISTANCE,),
    0x31: (CONTROL_FE_TARGET_POWER,),
    0x32: (CONTROL_FE_SIMULATION,),
    0x33: (CONTROL_FE_SIMULATION,),
    0x37: (CONTROL_FE_USER_CONFIGURATION,),
}


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    """Resolved capabilities plus human-readable evidence for diagnostics."""

    controls: frozenset[str]
    events: frozenset[str]
    evidence: tuple[tuple[str, str], ...]

    def supports_control(self, capability: str) -> bool:
        return capability in self.controls

    def supports_event(self, capability: str) -> bool:
        return capability in self.events


def is_running_power_source(device: AntDevice) -> bool:
    """Return True when Device Type 11 is clearly serving a running role."""
    profiles = set(device.profiles)
    if DEVICE_TYPE_POWER not in profiles:
        return False
    return bool(profiles & _RUNNING_POWER_COMPANION_PROFILES) and not bool(
        profiles & _CYCLING_COMPANION_PROFILES
    )


def _observed_pages(device: AntDevice, device_type: int) -> set[int]:
    pages = device.decoder_state.get("observed_pages", {}).get(device_type, set())
    if isinstance(pages, set):
        return {int(page) for page in pages}
    if isinstance(pages, (list, tuple, frozenset)):
        return {int(page) for page in pages}
    return set()


def _command_overrides(device: AntDevice) -> dict[str, bool]:
    raw = device.decoder_state.get("control_capability_overrides", {})
    return raw if isinstance(raw, dict) else {}


def _apply_override(
    controls: set[str],
    evidence: dict[str, str],
    overrides: dict[str, bool],
    capability: str,
) -> None:
    value = overrides.get(capability)
    if value is True:
        controls.add(capability)
        evidence[capability] = "confirmed by ANT+ command status"
    elif value is False:
        controls.discard(capability)
        evidence[capability] = "rejected/not-supported by ANT+ command status"


def capability_snapshot(device: AntDevice) -> CapabilitySnapshot:
    """Resolve every implemented control/event capability for one device."""
    profiles = set(device.profiles)
    controls: set[str] = set()
    events: set[str] = set()
    evidence: dict[str, str] = {}

    if DEVICE_TYPE_CONTROLS in profiles:
        # Generic Control is the semantic purpose of the Controls Device profile.
        controls.add(CONTROL_GENERIC)
        events.update({EVENT_GENERIC_CONTROL, EVENT_CONTROLS_AVAILABILITY})
        evidence[CONTROL_GENERIC] = "Controls Device profile"
        evidence[EVENT_GENERIC_CONTROL] = "Controls Device profile"
        evidence[EVENT_CONTROLS_AVAILABILITY] = "Controls Device profile"

    if DEVICE_TYPE_FITNESS_EQUIPMENT in profiles:
        # FE-C capability page 54 is required for the FE-C use case, so the
        # capability-request operation itself is always valid for this profile.
        controls.add(CONTROL_FE_REQUEST_CAPABILITIES)
        evidence[CONTROL_FE_REQUEST_CAPABILITIES] = "FE-C profile capability exchange"
        events.update({EVENT_FE_CALIBRATION, EVENT_FE_COMMAND_STATUS})
        evidence[EVENT_FE_CALIBRATION] = "FE-C profile"
        evidence[EVENT_FE_COMMAND_STATUS] = "FE-C profile"

        fe_caps = device.decoder_state.get("fe_capabilities")
        if isinstance(fe_caps, dict):
            if fe_caps.get("basic_resistance") is True:
                controls.add(CONTROL_FE_BASIC_RESISTANCE)
                evidence[CONTROL_FE_BASIC_RESISTANCE] = "FE-C capability page 54"
            if fe_caps.get("target_power") is True:
                controls.add(CONTROL_FE_TARGET_POWER)
                evidence[CONTROL_FE_TARGET_POWER] = "FE-C capability page 54"
            if fe_caps.get("simulation") is True:
                controls.add(CONTROL_FE_SIMULATION)
                evidence[CONTROL_FE_SIMULATION] = "FE-C capability page 54"

        fe_pages = _observed_pages(device, DEVICE_TYPE_FITNESS_EQUIPMENT)
        # User Configuration is optional in FE-C. Do not expose its entities
        # merely because simulation is supported; page 55 is positive evidence.
        if 0x37 in fe_pages:
            controls.add(CONTROL_FE_USER_CONFIGURATION)
            evidence[CONTROL_FE_USER_CONFIGURATION] = "observed FE-C user configuration page 55"

        # Calibration support has no complete mode bitmap in page 54. Positive
        # calibration traffic proves support. Until then we keep calibration
        # hidden rather than creating controls that may be meaningless.
        if 0x01 in fe_pages or 0x02 in fe_pages:
            controls.add(CONTROL_FE_ZERO_OFFSET_CALIBRATION)
            evidence[CONTROL_FE_ZERO_OFFSET_CALIBRATION] = "observed FE-C calibration traffic"
            # A progress page is strong evidence of spin-down support; a direct
            # calibration response can also be confirmation after command status.
            if 0x02 in fe_pages:
                controls.add(CONTROL_FE_SPINDOWN_CALIBRATION)
                evidence[CONTROL_FE_SPINDOWN_CALIBRATION] = "observed FE-C calibration progress"

    if DEVICE_TYPE_POWER in profiles and not is_running_power_source(device):
        # ANT+ Bicycle Power defines calibration for the cycling-power role. The
        # logical-role check prevents running devices that reuse type 11 from
        # inheriting cycling-only controls/events.
        controls.add(CONTROL_POWER_CALIBRATION)
        events.add(EVENT_POWER_CALIBRATION)
        evidence[CONTROL_POWER_CALIBRATION] = "Bicycle Power cycling role"
        evidence[EVENT_POWER_CALIBRATION] = "Bicycle Power cycling role"

    if DEVICE_TYPE_LEV in profiles:
        controls.add(CONTROL_LEV)
        evidence[CONTROL_LEV] = "LEV profile control role"

    if DEVICE_TYPE_DROPPER in profiles:
        controls.add(CONTROL_DROPPER)
        events.add(EVENT_DROPPER)
        evidence[CONTROL_DROPPER] = "Dropper Seatpost profile control role"
        evidence[EVENT_DROPPER] = "Dropper Seatpost profile"

    if DEVICE_TYPE_TIRE_PRESSURE in profiles:
        controls.add(CONTROL_TPMS_CONFIGURATION)
        evidence[CONTROL_TPMS_CONFIGURATION] = "TPMS writable parameter profile support"

    if DEVICE_TYPE_SHIFTING in profiles:
        events.add(EVENT_SHIFT)
        evidence[EVENT_SHIFT] = "Shifting profile"

    overrides = _command_overrides(device)
    for capability in (
        CONTROL_FE_BASIC_RESISTANCE,
        CONTROL_FE_TARGET_POWER,
        CONTROL_FE_SIMULATION,
        CONTROL_FE_USER_CONFIGURATION,
        CONTROL_FE_ZERO_OFFSET_CALIBRATION,
        CONTROL_FE_SPINDOWN_CALIBRATION,
    ):
        _apply_override(controls, evidence, overrides, capability)

    return CapabilitySnapshot(
        controls=frozenset(controls),
        events=frozenset(events),
        evidence=tuple(sorted(evidence.items())),
    )


def supports_control(device: AntDevice, capability: str) -> bool:
    return capability_snapshot(device).supports_control(capability)


def supports_event(device: AntDevice, capability: str) -> bool:
    return capability_snapshot(device).supports_event(capability)


def supports_bicycle_power_calibration(device: AntDevice) -> bool:
    """Backward-compatible helper used by older tests/callers."""
    return supports_control(device, CONTROL_POWER_CALIBRATION)


def record_observed_page(device: AntDevice, device_type: int, payload: bytes) -> bool:
    """Record one observed ANT page and return whether capability state changed."""
    before = capability_snapshot(device)
    if not payload:
        return False
    pages_by_profile = device.decoder_state.setdefault("observed_pages", {})
    pages = pages_by_profile.setdefault(device_type, set())
    if not isinstance(pages, set):
        pages = set(pages)
        pages_by_profile[device_type] = pages
    pages.add(int(payload[0]) & 0x7F)
    return capability_snapshot(device) != before


def record_fe_command_status(device: AntDevice, command_id: int, status_raw: int) -> bool:
    """Apply FE-C command-status feedback to capability overrides."""
    before = capability_snapshot(device)
    mapped = _FE_COMMAND_CAPABILITY.get(int(command_id), ())
    if not mapped:
        return False
    overrides = device.decoder_state.setdefault("control_capability_overrides", {})
    # pass confirms support; not_supported/rejected revoke. Fail/pending are not
    # capability statements and therefore leave the current decision intact.
    if status_raw == 0:
        for capability in mapped:
            overrides[capability] = True
    elif status_raw in (2, 3):
        for capability in mapped:
            overrides[capability] = False
    return capability_snapshot(device) != before


def capability_signature(device: AntDevice) -> tuple[Any, ...]:
    """Hashable capability signature used to notify HA platforms on changes."""
    snapshot = capability_snapshot(device)
    return (snapshot.controls, snapshot.events, snapshot.evidence)


def capability_attributes(device: AntDevice) -> dict[str, Any]:
    """Return diagnostic attributes suitable for logs/tests/future sensors."""
    snapshot = capability_snapshot(device)
    return {
        "controls": sorted(snapshot.controls),
        "events": sorted(snapshot.events),
        "evidence": dict(snapshot.evidence),
        "running_power_role": is_running_power_source(device),
    }
