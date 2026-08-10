"""Publicly documented ANT+ profile capability catalogue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentedProfile:
    device_type: int
    name: str
    capabilities: tuple[str, ...]
    passive_role: str
    active_features: tuple[str, ...] = ()


DOCUMENTED_PROFILES: dict[int, DocumentedProfile] = {
    1: DocumentedProfile(1, "Sync", ("ANT-FS file synchronization", "stored activity/file transfer"), "transport_only", ("ANT-FS pairing", "directory/file transfer")),
    11: DocumentedProfile(11, "Power Meter", ("instantaneous power", "average power", "cadence", "pedal power balance", "wheel/crank torque", "torque effectiveness", "pedal smoothness", "manufacturer/product/battery information"), "broadcast", ("calibration",)),
    15: DocumentedProfile(15, "Multi-Sport Speed/Distance", ("speed", "distance", "location/motion data", "manufacturer/product/battery information"), "broadcast"),
    16: DocumentedProfile(16, "Controls Device", ("menu up", "menu down", "select", "back", "home", "timer start", "timer stop", "timer reset", "lap", "length", "device availability"), "broadcast_commands"),
    17: DocumentedProfile(17, "Fitness Equipment", ("equipment type/state", "speed", "distance", "heart rate", "cycle length", "incline", "resistance", "metabolic data", "cadence", "power", "equipment capabilities", "calibration/status"), "broadcast", ("basic resistance control", "target power control", "simulation parameters", "user configuration", "calibration control")),
    18: DocumentedProfile(18, "Blood Pressure", ("systolic pressure", "diastolic pressure", "mean arterial pressure", "stored measurements"), "transport_only", ("ANT-FS measurement transfer",)),
    19: DocumentedProfile(19, "Geocache", ("beacon identification", "programmable geocache data"), "beacon", ("page requests", "programming/authentication")),
    20: DocumentedProfile(20, "Light Electric Vehicle", ("vehicle speed", "odometer/distance", "battery/energy", "assist state", "motor/system status", "manufacturer/product information"), "broadcast", ("assist/control commands",)),
    25: DocumentedProfile(25, "Environment", ("current temperature", "24-hour high temperature", "24-hour low temperature", "manufacturer/product/battery information"), "broadcast", ("stored data download",)),
    26: DocumentedProfile(26, "Racquet", ("stroke type", "racquet zone", "ball speed", "shot count", "shot selection", "swing accuracy", "capabilities", "summary data", "score", "session start", "session stop", "game marker", "set marker", "match marker", "ANT+ fitness data"), "broadcast", ("summary requests", "score/session marker upload", "ANT-FS FIT transfer")),
    30: DocumentedProfile(30, "Running Dynamics", ("running dynamics metrics", "cadence-related dynamics", "manufacturer/product/battery information"), "broadcast"),
    31: DocumentedProfile(31, "Muscle Oxygen", ("muscle oxygen saturation", "total haemoglobin", "session start", "session stop", "lap marker", "manufacturer/product/battery information"), "broadcast", ("ANT-FS stored session transfer",)),
    34: DocumentedProfile(34, "Shifting", ("front gear", "rear gear", "gear counts", "shift events", "invalid shifts", "shift failures", "trim index", "function-set events", "manufacturer/product/battery information"), "broadcast"),
    35: DocumentedProfile(35, "Bicycle Lights", ("light state", "light mode", "light network/status", "battery information"), "broadcast", ("light commands", "network configuration")),
    38: DocumentedProfile(38, "Extended Display", ("aggregated ANT+ fitness data", "display configuration", "alerts", "current screen index", "capabilities"), "bidirectional", ("display settings", "configuration", "capability exchange")),
    40: DocumentedProfile(40, "Radar", ("radar threat/target information", "relative target data", "radar state", "manufacturer/product/battery information"), "broadcast", ("radar/display control features",)),
    41: DocumentedProfile(41, "Tracker", ("asset identification", "asset name", "asset colour", "asset location", "distance", "bearing", "GPS-lost status", "low-battery status", "remove-asset status", "up to 20 assets", "manufacturer/product/battery information"), "broadcast", ("asset identification request", "disconnect command")),
    48: DocumentedProfile(48, "Tire Pressure Monitor", ("tire pressure", "sensor/status information", "manufacturer/product/battery information"), "broadcast"),
    115: DocumentedProfile(115, "Dropper Seatpost", ("seatpost status", "manufacturer/product information", "battery status"), "broadcast", ("seatpost commands",)),
    116: DocumentedProfile(116, "Suspension", ("fork/rear shock status", "lock state", "damping/settings", "automatic adjustment state", "manufacturer/product/battery information"), "broadcast", ("suspension setting adjustments",)),
    119: DocumentedProfile(119, "Weight Scale", ("weight", "hydration percentage", "body fat percentage", "active metabolic rate", "basal metabolic rate", "muscle mass", "bone mass", "user profile"), "broadcast", ("user profile transfer", "ANT-FS stored data transfer")),
    120: DocumentedProfile(120, "Heart Rate", ("heart rate", "heart beat count", "heart beat event time", "operating time", "manufacturer/product information", "battery status"), "broadcast"),
    121: DocumentedProfile(121, "Bike Speed/Cadence", ("speed event data", "cadence event data", "manufacturer/product/battery information"), "broadcast"),
    122: DocumentedProfile(122, "Bike Cadence", ("cadence event data", "manufacturer/product/battery information"), "broadcast"),
    123: DocumentedProfile(123, "Bike Speed", ("speed event data", "manufacturer/product/battery information"), "broadcast"),
    124: DocumentedProfile(124, "Stride Speed/Distance", ("speed", "distance", "stride count", "cadence", "calories", "location/motion status", "manufacturer/product/battery information"), "broadcast"),
    127: DocumentedProfile(127, "Core Temperature", ("core temperature", "quality/status", "manufacturer/product/battery information"), "broadcast"),
}

DOCUMENTED_FAMILIES_WITHOUT_CONFIRMED_DEVICE_TYPE = (
    "Pressure Sensor Array",
    "Short Message",
    "Multi-Sport GPS",
)


def documented_profile_types() -> set[int]:
    return set(DOCUMENTED_PROFILES)


def documented_profile_rows() -> list[dict[str, object]]:
    return [
        {
            "device_type": item.device_type,
            "name": item.name,
            "capabilities": list(item.capabilities),
            "passive_role": item.passive_role,
            "active_features": list(item.active_features),
        }
        for item in sorted(DOCUMENTED_PROFILES.values(), key=lambda row: row.device_type)
    ]
