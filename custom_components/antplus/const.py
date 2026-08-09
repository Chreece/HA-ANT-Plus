"""Constants for the ANT+ integration."""

DOMAIN = "antplus"
PLATFORMS = ["sensor", "switch"]

ANTPLUS_NETWORK_NUMBER = 0
ANTPLUS_RF_FREQUENCY = 57
DEFAULT_INACTIVITY_TIMEOUT = 30
DEVICE_INACTIVITY_TIMEOUT = 60

REMOTE_PACKET_EVENT = "antplus_remote_packet"

REMOTE_GATEWAY_HELLO_EVENT = "antplus_gateway_hello"
REMOTE_GATEWAY_STATUS_EVENT = "antplus_gateway_status"
REMOTE_CAPTURE_STATE_EVENT = "antplus_capture_state"

DEVICE_TYPE_POWER = 11
DEVICE_TYPE_CONTROLS = 16
DEVICE_TYPE_FITNESS_EQUIPMENT = 17
DEVICE_TYPE_BLOOD_PRESSURE = 18
DEVICE_TYPE_GEOCACHE = 19
DEVICE_TYPE_LEV = 20
DEVICE_TYPE_ENVIRONMENT = 25
DEVICE_TYPE_SHIFTING = 34
DEVICE_TYPE_BICYCLE_LIGHTS = 35
DEVICE_TYPE_RADAR = 40
DEVICE_TYPE_TIRE_PRESSURE = 48
DEVICE_TYPE_DROPPER = 115
DEVICE_TYPE_WEIGHT_SCALE = 119
DEVICE_TYPE_HEART_RATE = 120
DEVICE_TYPE_BIKE_SPEED_CADENCE = 121
DEVICE_TYPE_BIKE_CADENCE = 122
DEVICE_TYPE_BIKE_SPEED = 123
DEVICE_TYPE_STRIDE_SPEED = 124
DEVICE_TYPE_CORE_TEMP = 127

DEVICE_TYPE_NAMES = {
    11: "Power Meter",
    16: "Controls Device",
    17: "Fitness Equipment",
    18: "Blood Pressure",
    19: "Geocache",
    20: "Light Electric Vehicle",
    25: "Environment",
    34: "Shifting",
    35: "Bicycle Lights",
    40: "Radar",
    48: "Tire Pressure Monitor",
    115: "Dropper Seatpost",
    119: "Weight Scale",
    120: "Heart Rate",
    121: "Bike Speed/Cadence",
    122: "Bike Cadence",
    123: "Bike Speed",
    124: "Stride Speed/Distance",
    127: "Core Temperature",
}

MANUFACTURERS = {
    1: "Garmin",
    95: "Stryd",
}

BATTERY_STATUS_NAMES = {
    0: "Unknown",
    1: "New",
    2: "Good",
    3: "OK",
    4: "Low",
    5: "Critical",
    6: "Charging",
    7: "Invalid",
}


def profile_name(device_type: int) -> str:
    """Return a human-readable ANT+ profile name."""
    return DEVICE_TYPE_NAMES.get(device_type, f"Unknown Profile {device_type}")


def device_display_name(device) -> str:
    """Build a universal display name from broadcast metadata."""
    known_profiles = sorted(
        profile for profile in device.profiles if profile in DEVICE_TYPE_NAMES
    )
    manufacturer = device.manufacturer_name
    if manufacturer and manufacturer.startswith("ANT manufacturer "):
        manufacturer = None

    if len(known_profiles) == 1:
        profile = profile_name(known_profiles[0])
        return (
            f"{manufacturer} {profile} {device.device_id}"
            if manufacturer
            else f"{profile} {device.device_id}"
        )

    if len(known_profiles) > 1:
        return (
            f"{manufacturer} ANT+ {device.device_id}"
            if manufacturer
            else f"ANT+ {device.device_id}"
        )

    return (
        f"{manufacturer} ANT+ {device.device_id}"
        if manufacturer
        else f"ANT+ Device {device.device_id}"
    )


def device_model_name(device) -> str:
    """Build model text from all known profiles."""
    known_profiles = sorted(
        profile for profile in device.profiles if profile in DEVICE_TYPE_NAMES
    )
    if not known_profiles:
        return f"ANT+ ID {device.device_id}"
    return " + ".join(profile_name(profile) for profile in known_profiles)
