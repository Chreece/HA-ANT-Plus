"""Semantic ANT+ events for Home Assistant automations."""
from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    ANTPLUS_EVENT,
    DEVICE_TYPE_CONTROLS,
    DEVICE_TYPE_DROPPER,
    DEVICE_TYPE_FITNESS_EQUIPMENT,
    DEVICE_TYPE_POWER,
    DEVICE_TYPE_SHIFTING,
    DOMAIN,
    profile_name,
)
from .capabilities import (
    EVENT_CONTROLS_AVAILABILITY,
    EVENT_DROPPER,
    EVENT_FE_CALIBRATION,
    EVENT_FE_COMMAND_STATUS,
    EVENT_GENERIC_CONTROL,
    EVENT_POWER_CALIBRATION,
    EVENT_SHIFT,
    supports_event,
)
from .models import AntDevice
from .receiver import AntPlusReceiver

_LOGGER = logging.getLogger(__name__)

CONTROL_COMMANDS = {
    0: "menu_up",
    1: "menu_down",
    2: "select",
    3: "back",
    4: "home",
    32: "timer_start",
    33: "timer_stop",
    34: "timer_reset",
    35: "length",
    36: "lap",
}


def async_register_event_dispatcher(
    hass: HomeAssistant,
    entry: ConfigEntry,
    receiver: AntPlusReceiver,
) -> Callable[[], None]:
    """Turn event-oriented ANT+ packets into one stable HA bus event."""

    def emit(device: AntDevice, device_type: int, event_name: str, data: dict) -> None:
        event_data = {
            "device_id": device.device_id,
            "device_type": device_type,
            "profile": profile_name(device_type),
            "event": event_name,
            **data,
        }
        hass.loop.call_soon_threadsafe(hass.bus.async_fire, ANTPLUS_EVENT, event_data)

    def packet(
        device: AntDevice,
        device_type: int,
        transmission_type: int,
        payload: bytes,
        source: str,
    ) -> None:
        # ANT+ Controls Device generic command page (0x49). Commands are ACK
        # packets, but scan/gateway transport presents all received packet
        # types through the same confirmed packet callback.
        if (
            device_type == DEVICE_TYPE_CONTROLS
            and payload[0] == 0x02
            and supports_event(device, EVENT_CONTROLS_AVAILABILITY)
        ):
            availability_key = (payload[1], payload[7])
            if device.decoder_state.get("controls_availability_event") == availability_key:
                return
            device.decoder_state["controls_availability_event"] = availability_key
            emit(
                device,
                device_type,
                "device_available",
                {
                    "current_notifications": payload[1],
                    "capabilities_raw": payload[7],
                    "transmission_type": transmission_type,
                    "source": source,
                },
            )
            return

        if (
            device_type == DEVICE_TYPE_CONTROLS
            and payload[0] == 0x49
            and supports_event(device, EVENT_GENERIC_CONTROL)
        ):
            sequence = payload[5]
            command_raw = payload[6] | (payload[7] << 8)
            key = (sequence, command_raw)
            state_key = "controls_last_event"
            if device.decoder_state.get(state_key) == key:
                return
            device.decoder_state[state_key] = key
            event_name = CONTROL_COMMANDS.get(command_raw, "custom_command")
            emit(
                device,
                device_type,
                event_name,
                {
                    "command": event_name,
                    "command_raw": command_raw,
                    "sequence": sequence,
                    "slave_serial": payload[1] | (payload[2] << 8),
                    "slave_manufacturer_id": payload[3] | (payload[4] << 8),
                    "transmission_type": transmission_type,
                    "source": source,
                },
            )
            return

        if (
            device_type == DEVICE_TYPE_FITNESS_EQUIPMENT
            and (payload[0] & 0x7F) in (0x01, 0x02)
            and supports_event(device, EVENT_FE_CALIBRATION)
        ):
            page = payload[0] & 0x7F
            if page == 0x01:
                response = payload[1]
                key = (page, bytes(payload[1:8]))
                if device.decoder_state.get("fe_calibration_event") == key:
                    return
                device.decoder_state["fe_calibration_event"] = key
                emit(
                    device,
                    device_type,
                    "calibration_response",
                    {
                        "zero_offset_success": bool(response & 0x40),
                        "spin_down_success": bool(response & 0x80),
                        "temperature_raw": payload[3],
                        "zero_offset_raw": payload[4] | (payload[5] << 8),
                        "spin_down_time_raw": payload[6] | (payload[7] << 8),
                        "transmission_type": transmission_type,
                        "source": source,
                    },
                )
            else:
                key = (page, bytes(payload[1:8]))
                if device.decoder_state.get("fe_calibration_progress_event") == key:
                    return
                device.decoder_state["fe_calibration_progress_event"] = key
                emit(
                    device,
                    device_type,
                    "calibration_progress",
                    {
                        "zero_offset_pending": bool(payload[1] & 0x40),
                        "spin_down_pending": bool(payload[1] & 0x80),
                        "temperature_raw": payload[3],
                        "target_speed_raw": payload[4] | (payload[5] << 8),
                        "target_spin_down_time_raw": payload[6] | (payload[7] << 8),
                        "transmission_type": transmission_type,
                        "source": source,
                    },
                )
            return

        if (
            device_type == DEVICE_TYPE_FITNESS_EQUIPMENT
            and (payload[0] & 0x7F) == 0x47
            and supports_event(device, EVENT_FE_COMMAND_STATUS)
        ):
            command_id = payload[1]
            status_raw = payload[3]
            key = (command_id, status_raw, bytes(payload[4:8]))
            if device.decoder_state.get("fe_command_status_event") == key:
                return
            device.decoder_state["fe_command_status_event"] = key
            emit(
                device,
                device_type,
                "command_status",
                {
                    "command_id": command_id,
                    "status": {0: "pass", 1: "fail", 2: "not_supported", 3: "rejected", 4: "pending", 255: "uninitialized"}.get(status_raw, "unknown"),
                    "status_raw": status_raw,
                    "response_raw": payload[4:8].hex(),
                    "transmission_type": transmission_type,
                    "source": source,
                },
            )
            return

        if (
            device_type == DEVICE_TYPE_POWER
            and (payload[0] & 0x7F) == 0x01
            and supports_event(device, EVENT_POWER_CALIBRATION)
        ):
            key = bytes(payload[1:8])
            if device.decoder_state.get("power_calibration_event") == key:
                return
            device.decoder_state["power_calibration_event"] = key
            emit(
                device,
                device_type,
                "calibration_response",
                {
                    "calibration_id": payload[1],
                    "data_raw": payload[2:8].hex(),
                    "transmission_type": transmission_type,
                    "source": source,
                },
            )
            return

        # Shifting page 1 has an 8-bit shift event counter. The first packet
        # establishes state; only subsequent counter changes become events.
        if (
            device_type == DEVICE_TYPE_SHIFTING
            and (payload[0] & 0x7F) == 0x01
            and supports_event(device, EVENT_SHIFT)
        ):
            count = payload[1]
            old = device.decoder_state.get("ha_event_shift_count")
            device.decoder_state["ha_event_shift_count"] = count
            if old is None or old == count:
                return
            emit(
                device,
                device_type,
                "shift",
                {
                    "event_count": count,
                    "event_delta": (count - int(old)) & 0xFF,
                    "rear_gear": payload[3] & 0x1F,
                    "front_gear": (payload[3] >> 5) & 0x07,
                    "rear_gear_count": payload[4] & 0x1F,
                    "front_gear_count": (payload[4] >> 5) & 0x07,
                    "invalid_rear_inboard_shifts": payload[5] & 0x0F,
                    "invalid_rear_outboard_shifts": (payload[5] >> 4) & 0x0F,
                    "invalid_front_inboard_shifts": payload[6] & 0x0F,
                    "invalid_front_outboard_shifts": (payload[6] >> 4) & 0x0F,
                    "rear_shift_failures": payload[7] & 0x0F,
                    "front_shift_failures": (payload[7] >> 4) & 0x0F,
                    "transmission_type": transmission_type,
                    "source": source,
                },
            )
            return

        # Dropper page 1 increments its event counter when the valve changes.
        if (
            device_type == DEVICE_TYPE_DROPPER
            and (payload[0] & 0x7F) == 0x01
            and supports_event(device, EVENT_DROPPER)
        ):
            count = payload[4] | (payload[5] << 8)
            valve_unlocked = bool(payload[7] & 0x80)
            old = device.decoder_state.get("ha_event_dropper_count")
            device.decoder_state["ha_event_dropper_count"] = count
            if old is None or old == count:
                return
            emit(
                device,
                device_type,
                "unlocked" if valve_unlocked else "locked",
                {
                    "event_count": count,
                    "event_delta": (count - int(old)) & 0xFFFF,
                    "valve_state": "unlocked" if valve_unlocked else "locked",
                    "configured_unlock_delay": None
                    if (payload[6] & 0x7F) == 0x7F
                    else (payload[6] & 0x7F) / 100.0,
                    "transmission_type": transmission_type,
                    "source": source,
                },
            )

    return receiver.add_packet_callback(packet)
