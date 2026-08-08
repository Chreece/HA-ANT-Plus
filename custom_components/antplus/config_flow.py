"""Config flow for ANT+."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.usb import UsbServiceInfo

from .const import DEFAULT_INACTIVITY_TIMEOUT, DOMAIN
from .receiver import AntPlusReceiver


UNIQUE_ID = "antplus_usb_hub"


class AntPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the ANT+ USB hub."""

    VERSION = 1

    def __init__(self) -> None:
        self._usb_info: UsbServiceInfo | None = None

    @staticmethod
    def async_get_options_flow(config_entry):
        return AntPlusOptionsFlow(config_entry)

    async def _async_validate_adapter(self) -> str | None:
        """Try to open the ANT+ adapter before creating the config entry."""
        receiver = AntPlusReceiver()

        try:
            await self.hass.async_add_executor_job(receiver.start)

            if receiver.running:
                return None

            error = receiver.error or "ANT+ adapter did not enter running state"
            error_lower = error.lower()

            if (
                "resource busy" in error_lower
                or "already in use" in error_lower
                or "busy" in error_lower
            ):
                return "adapter_in_use"

            if (
                "permission" in error_lower
                or "access denied" in error_lower
                or "operation not permitted" in error_lower
            ):
                return "permission_denied"

            if (
                "no ant" in error_lower
                or "not found" in error_lower
                or "no device" in error_lower
            ):
                return "adapter_not_found"

            return "cannot_start"

        except Exception:
            return "cannot_start"

        finally:
            try:
                await self.hass.async_add_executor_job(receiver.stop)
            except Exception:
                pass

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual setup."""

        await self.async_set_unique_id(UNIQUE_ID)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            error = await self._async_validate_adapter()

            if error is None:
                return self.async_create_entry(
                    title="HA ANT+ USB Adapter",
                    data={},
                )

            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            errors=errors,
        )

    async def async_step_usb(
        self, discovery_info: UsbServiceInfo
    ) -> FlowResult:
        """Handle USB discovery."""

        self._usb_info = discovery_info

        # This integration owns one ANT+ USB hub. Using one stable unique ID
        # prevents manual setup and USB discovery from creating duplicates.
        await self.async_set_unique_id(UNIQUE_ID)
        self._abort_if_unique_id_configured()

        return await self.async_step_usb_confirm()

    async def async_step_usb_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm a discovered ANT+ USB adapter."""

        errors: dict[str, str] = {}

        if user_input is not None:
            error = await self._async_validate_adapter()

            if error is None:
                return self.async_create_entry(
                    title="HA ANT+ USB Adapter",
                    data={},
                )

            errors["base"] = error

        name = "HA ANT+ USB Adapter"

        if self._usb_info is not None:
            manufacturer = self._usb_info.manufacturer
            product = self._usb_info.description

            if manufacturer and product:
                name = f"{manufacturer} {product}"
            elif product:
                name = product
            elif manufacturer:
                name = f"{manufacturer} ANT+ USB Adapter"

        return self.async_show_form(
            step_id="usb_confirm",
            description_placeholders={"name": name},
            errors=errors,
        )


class AntPlusOptionsFlow(config_entries.OptionsFlow):
    """ANT+ options."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "inactivity_timeout",
                        default=self.config_entry.options.get(
                            "inactivity_timeout",
                            DEFAULT_INACTIVITY_TIMEOUT,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=5, max=300),
                    )
                }
            ),
        )
