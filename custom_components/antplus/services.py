"""Home Assistant service actions for advanced ANT+ transmit operations."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .capabilities import CONTROL_GENERIC, supports_control
from .control import (
    GENERIC_CONTROL_COMMANDS,
    controls_generic_payload,
    parse_raw_payload,
    request_data_page_payload,
)
from .diagnostics import log_diagnostics

SERVICE_SEND_RAW_CONTROL = "send_raw_control"
SERVICE_REQUEST_DATA_PAGE = "request_data_page"
SERVICE_SEND_GENERIC_CONTROL = "send_generic_control"
SERVICE_DUMP_DIAGNOSTICS = "dump_diagnostics"
SERVICE_RESET_DIAGNOSTICS = "reset_diagnostics"

COMMON = {
    vol.Required("device_id"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
    vol.Required("device_type"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Required("period"): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    vol.Optional("transmission_type"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
}

SEND_RAW_SCHEMA = vol.Schema({
    **COMMON,
    vol.Required("payload"): cv.string,
})

GENERIC_CONTROL_SCHEMA = vol.Schema({
    vol.Required("device_id"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
    vol.Optional("transmission_type"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Required("command"): vol.In(tuple(GENERIC_CONTROL_COMMANDS)),
    vol.Optional("controller_serial", default=0xFFFF): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
    vol.Optional("controller_manufacturer_id", default=0xFFFF): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
})

REQUEST_PAGE_SCHEMA = vol.Schema({
    **COMMON,
    vol.Required("page"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Optional("count", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=127)),
})


def async_register_services(hass: HomeAssistant, receiver) -> None:
    """Register advanced transmit services for the single HA ANT+ entry."""
    async def send_raw(call: ServiceCall) -> None:
        await receiver.adapter_manager.async_send_control(
            device_id=call.data["device_id"],
            device_type=call.data["device_type"],
            transmission_type=call.data.get("transmission_type"),
            period=call.data["period"],
            payload=parse_raw_payload(call.data["payload"]),
        )

    async def send_generic_control(call: ServiceCall) -> None:
        device = receiver.devices.get(call.data["device_id"])
        if device is None:
            raise ServiceValidationError("ANT+ device has not been discovered")
        if not supports_control(device, CONTROL_GENERIC):
            raise ServiceValidationError(
                "ANT+ Generic Control is not supported by this device's resolved capabilities"
            )
        state = device.decoder_state.setdefault("controls_tx", {})
        sequence = (int(state.get("sequence", 0)) + 1) & 0xFF
        state["sequence"] = sequence
        await receiver.adapter_manager.async_send_control(
            device_id=call.data["device_id"],
            device_type=16,
            transmission_type=call.data.get("transmission_type"),
            period=8192,
            payload=controls_generic_payload(
                call.data["command"],
                sequence=sequence,
                controller_serial=call.data["controller_serial"],
                controller_manufacturer_id=call.data["controller_manufacturer_id"],
            ),
        )

    async def request_page(call: ServiceCall) -> None:
        await receiver.adapter_manager.async_send_control(
            device_id=call.data["device_id"],
            device_type=call.data["device_type"],
            transmission_type=call.data.get("transmission_type"),
            period=call.data["period"],
            payload=request_data_page_payload(call.data["page"], call.data["count"]),
        )

    async def dump_diagnostics(_call: ServiceCall) -> None:
        log_diagnostics(receiver.diagnostics)

    async def reset_diagnostics(_call: ServiceCall) -> None:
        receiver.diagnostics.reset()

    hass.services.async_register(DOMAIN, SERVICE_SEND_RAW_CONTROL, send_raw, schema=SEND_RAW_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REQUEST_DATA_PAGE, request_page, schema=REQUEST_PAGE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_GENERIC_CONTROL, send_generic_control, schema=GENERIC_CONTROL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DUMP_DIAGNOSTICS, dump_diagnostics)
    hass.services.async_register(DOMAIN, SERVICE_RESET_DIAGNOSTICS, reset_diagnostics)


def async_unregister_services(hass: HomeAssistant) -> None:
    for service in (
        SERVICE_SEND_RAW_CONTROL,
        SERVICE_REQUEST_DATA_PAGE,
        SERVICE_SEND_GENERIC_CONTROL,
        SERVICE_DUMP_DIAGNOSTICS,
        SERVICE_RESET_DIAGNOSTICS,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
