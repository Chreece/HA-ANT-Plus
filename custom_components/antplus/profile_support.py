"""Truthful ANT+ profile implementation matrix."""
from __future__ import annotations
from dataclasses import dataclass
from .const import DEVICE_TYPE_NAMES

@dataclass(frozen=True, slots=True)
class ProfileSupport:
    device_type: int
    name: str
    mode: str
    detail: str

# Modes: native, openant_fallback, antfs, active_protocol, spec_required.
PROFILE_MODES = {
    1: ("antfs", "FIT file transfer over ANT-FS; not a passive real-time sensor."),
    11: ("native", "Native Bicycle Power broadcast decoder."),
    15: ("spec_required", "Recognized losslessly; semantic page layout requires the profile specification."),
    16: ("openant_fallback", "OpenANT fallback currently available; native port pending."),
    17: ("native", "Native Fitness Equipment broadcast decoder; FE-C control is separate."),
    18: ("antfs", "Blood Pressure measurements are stored in FIT and transferred using ANT-FS."),
    19: ("active_protocol", "Beacon discovery is passive; semantic exchange requires active requests."),
    20: ("openant_fallback", "OpenANT fallback currently available; native port pending."),
    25: ("openant_fallback", "OpenANT fallback currently available; native port pending."),
    26: ("spec_required", "Recognized losslessly; exact Racquet stroke page layout is not guessed."),
    30: ("spec_required", "Recognized losslessly; exact Running Dynamics page layout is not guessed."),
    31: ("spec_required", "Recognized losslessly; exact SmO2/THb page layout requires the profile specification."),
    34: ("native", "Native Shifting status and trim decoder."),
    35: ("spec_required", "Recognized losslessly; exact Bicycle Lights page layout is not guessed."),
    40: ("spec_required", "Recognized losslessly; exact Radar target page layout is not guessed."),
    41: ("spec_required", "Recognized losslessly; exact Tracker asset page layout requires the profile specification."),
    48: ("openant_fallback", "OpenANT fallback currently available; native port pending."),
    115: ("openant_fallback", "OpenANT fallback currently available; commands are a separate active-control feature."),
    116: ("spec_required", "Recognized losslessly; exact Suspension status/settings layout requires the profile specification."),
    119: ("spec_required", "Recognized losslessly; exact Weight Scale/body-composition layout requires the profile specification."),
    120: ("native", "Native Heart Rate broadcast decoder."),
    121: ("native", "Native Bike Speed/Cadence decoder."),
    122: ("native", "Native Bike Cadence decoder."),
    123: ("native", "Native Bike Speed decoder."),
    124: ("native", "Native Stride Speed/Distance decoder."),
    127: ("openant_fallback", "OpenANT fallback where available; native port pending."),
}

PROFILE_SUPPORT = {
    device_type: ProfileSupport(device_type, DEVICE_TYPE_NAMES[device_type], mode, detail)
    for device_type, (mode, detail) in PROFILE_MODES.items()
    if device_type in DEVICE_TYPE_NAMES
}

def native_profile_types() -> set[int]:
    return {k for k, v in PROFILE_SUPPORT.items() if v.mode == "native"}

def profile_support_rows() -> list[dict[str, object]]:
    return [
        {"device_type": v.device_type, "name": v.name, "mode": v.mode, "detail": v.detail}
        for v in sorted(PROFILE_SUPPORT.values(), key=lambda item: item.device_type)
    ]
