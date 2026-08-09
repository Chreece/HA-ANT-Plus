"""Config flow for HA ANT+."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.usb import UsbServiceInfo

from .const import DEFAULT_INACTIVITY_TIMEOUT, DOMAIN

UNIQUE_ID = "antplus_hub"


class AntPlusConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Configure HA ANT+."""

    VERSION = 2

    def __init__(self) -> None:
        self._usb_info: UsbServiceInfo | None = None

    @staticmethod
    def async_get_options_flow(config_entry):
        return AntPlusOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Set up HA ANT+ manually.

        No transport selection is required. Once configured, HA ANT+
        accepts both local USB packets and remote packets automatically.
        """
        await self.async_set_unique_id(UNIQUE_ID)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="HA ANT+",
                data={},
            )

        return self.async_show_form(
            step_id="user",
        )

    async def async_step_usb(
        self,
        discovery_info: UsbServiceInfo,
    ) -> FlowResult:
        """Handle automatic discovery of a local ANT USB adapter."""
        self._usb_info = discovery_info

        await self.async_set_unique_id(UNIQUE_ID)
        self._abort_if_unique_id_configured()

        return await self.async_step_usb_confirm()

    async def async_step_usb_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm setup after local USB discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title="HA ANT+",
                data={},
            )

        name = "ANT+ USB Adapter"

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
        )


class AntPlusOptionsFlow(config_entries.OptionsFlow):
    """HA ANT+ options."""

    async def async_step_init(
        self,
        user_input=None,
    ):
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=user_input,
            )

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
