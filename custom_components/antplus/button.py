# Button platform for HA ANT+ maintenance actions.

from __future__ import annotations

import logging
import re

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_TYPE_CONTROLS,
    DEVICE_TYPE_FITNESS_EQUIPMENT,
    DEVICE_TYPE_POWER,
    DOMAIN,
)
from .subentries import ensure_sensor_subentry
from .receiver import AntPlusReceiver
from .control import (
    GENERIC_CONTROL_COMMANDS,
    async_send,
    bicycle_power_manual_calibration_payload,
    controls_generic_payload,
    device_control_available,
    fe_calibration_payload,
    request_data_page_payload,
)
from .entity import AntPlusEntity
from .models import AntDevice

_LOGGER = logging.getLogger(__name__)

_RAW_LAST_PAGE_RE = re.compile(r"^\d+_profile_\d+_last_page$")
_RAW_PAGE_RE = re.compile(r"^\d+_profile_\d+_page_\d+_raw$")


def _is_raw_fallback_unique_id(unique_id: str) -> bool:
    return bool(
        _RAW_LAST_PAGE_RE.fullmatch(unique_id)
        or _RAW_PAGE_RE.fullmatch(unique_id)
    )


def _numeric_ant_identifier(device: dr.DeviceEntry) -> int | None:
    for domain, value in device.identifiers:
        if domain != DOMAIN:
            continue
        value_str = str(value)
        if value_str.isdigit():
            return int(value_str)
    return None


async def async_cleanup_stale_raw_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    receiver: AntPlusReceiver,
) -> list[int]:
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    confirmed_ids = set(receiver.devices)
    removed: list[int] = []

    for device in list(device_registry.devices.values()):
        if entry.entry_id not in device.config_entries:
            continue

        ant_id = _numeric_ant_identifier(device)
        if ant_id is None or ant_id in confirmed_ids:
            continue

        entities = [
            entity
            for entity in entity_registry.entities.values()
            if entity.device_id == device.id and entity.platform == DOMAIN
        ]

        if not entities:
            continue

        if not all(
            _is_raw_fallback_unique_id(entity.unique_id or "")
            for entity in entities
        ):
            continue

        for entity in list(entities):
            entity_registry.async_remove(entity.entity_id)

        device_registry.async_remove_device(device.id)
        removed.append(ant_id)

        _LOGGER.info(
            "Removed stale raw-only ANT+ device %s (%d fallback entities)",
            ant_id,
            len(entities),
        )

    return sorted(removed)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    receiver: AntPlusReceiver = hass.data[DOMAIN][entry.entry_id]
    sensors_subentry_id = ensure_sensor_subentry(hass, entry)
    async_add_entities(
        [AntPlusCleanupStaleDevicesButton(hass, entry, receiver)],
        update_before_add=False,
        config_subentry_id=sensors_subentry_id,
    )

    known_controls: set[tuple[int, str]] = set()

    def add_device_controls(device: AntDevice) -> None:
        entities: list[ButtonEntity] = []
        specs: list[tuple[str, type[ButtonEntity], tuple]] = []
        if DEVICE_TYPE_CONTROLS in device.profiles:
            for command in GENERIC_CONTROL_COMMANDS:
                specs.append((f"controls_{command}", AntGenericControlButton, (command,)))
        if DEVICE_TYPE_FITNESS_EQUIPMENT in device.profiles:
            specs.extend((
                ("fe_calibrate_zero_offset", AntFeCalibrationButton, ("zero_offset",)),
                ("fe_calibrate_spin_down", AntFeCalibrationButton, ("spin_down",)),
                ("fe_calibrate_both", AntFeCalibrationButton, ("both",)),
                ("fe_cancel_calibration", AntFeCalibrationButton, ("cancel",)),
                ("fe_request_capabilities", AntFeRequestCapabilitiesButton, ()),
            ))
        if DEVICE_TYPE_POWER in device.profiles:
            specs.append(("power_manual_calibration", AntPowerCalibrationButton, ()))

        for key, cls, args in specs:
            ident = (device.device_id, key)
            if ident in known_controls:
                continue
            known_controls.add(ident)
            entities.append(cls(receiver, device, *args))
        if entities:
            async_add_entities(
                entities,
                update_before_add=False,
                config_subentry_id=sensors_subentry_id,
            )

    for device in receiver.snapshot().values():
        add_device_controls(device)

    def device_changed(device: AntDevice) -> None:
        hass.loop.call_soon_threadsafe(add_device_controls, device)

    entry.async_on_unload(receiver.add_device_callback(device_changed))


class AntPlusCleanupStaleDevicesButton(ButtonEntity):
    _attr_name = "Clean stale ANT+ devices"
    _attr_unique_id = "antplus_sensors_cleanup_stale_devices"
    _attr_icon = "mdi:broom"
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        receiver: AntPlusReceiver,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._receiver = receiver
        self._last_removed: list[int] = []


    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self):
        return {
            "scope": "all_ant_sensors",
            "confirmed_ant_devices": sorted(self._receiver.devices),
            "last_removed_count": len(self._last_removed),
            "last_removed_ant_ids": self._last_removed,
        }

    async def async_press(self) -> None:
        self._last_removed = await async_cleanup_stale_raw_devices(
            self._hass,
            self._entry,
            self._receiver,
        )
        _LOGGER.info(
            "ANT+ stale-device cleanup completed: removed %d device(s): %s",
            len(self._last_removed),
            self._last_removed,
        )
        self.async_write_ha_state()


class _AntDeviceControlButton(AntPlusEntity, ButtonEntity):
    control_profile: int

    def __init__(self, receiver, device, key: str, name: str, icon: str) -> None:
        AntPlusEntity.__init__(self, receiver, device, "__control__")
        self._attr_unique_id = f"{device.device_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return device_control_available(
            self.receiver, self.ant_device_id, self.control_profile
        )


class AntGenericControlButton(_AntDeviceControlButton):
    control_profile = DEVICE_TYPE_CONTROLS

    _NAMES = {
        "menu_up": ("Menu Up", "mdi:menu-up"),
        "menu_down": ("Menu Down", "mdi:menu-down"),
        "select": ("Select", "mdi:gesture-tap-button"),
        "back": ("Back", "mdi:arrow-left"),
        "home": ("Home", "mdi:home"),
        "timer_start": ("Timer Start", "mdi:play"),
        "timer_stop": ("Timer Stop", "mdi:stop"),
        "timer_reset": ("Timer Reset", "mdi:restart"),
        "length": ("Length", "mdi:pool"),
        "lap": ("Lap", "mdi:flag-checkered"),
    }

    def __init__(self, receiver, device, command: str) -> None:
        self.command = command
        name, icon = self._NAMES[command]
        super().__init__(receiver, device, f"controls_{command}", name, icon)

    async def async_press(self) -> None:
        state = self.ant_device.decoder_state.setdefault("controls_tx", {})
        sequence = (int(state.get("sequence", 0)) + 1) & 0xFF
        state["sequence"] = sequence
        await async_send(
            self.receiver,
            self.ant_device_id,
            self.control_profile,
            controls_generic_payload(self.command, sequence=sequence),
        )


class AntFeCalibrationButton(_AntDeviceControlButton):
    control_profile = DEVICE_TYPE_FITNESS_EQUIPMENT

    _MODES = {
        "zero_offset": ("Calibrate Zero Offset", "mdi:scale-balance", True, False),
        "spin_down": ("Calibrate Spin Down", "mdi:rotate-360", False, True),
        "both": ("Calibrate Zero Offset + Spin Down", "mdi:tune", True, True),
        "cancel": ("Cancel Calibration", "mdi:cancel", False, False),
    }

    def __init__(self, receiver, device, mode: str) -> None:
        self.mode = mode
        name, icon, _zero, _spin = self._MODES[mode]
        super().__init__(receiver, device, f"fe_calibrate_{mode}", name, icon)

    async def async_press(self) -> None:
        _name, _icon, zero, spin = self._MODES[self.mode]
        await async_send(
            self.receiver,
            self.ant_device_id,
            self.control_profile,
            fe_calibration_payload(zero_offset=zero, spin_down=spin),
        )


class AntFeRequestCapabilitiesButton(_AntDeviceControlButton):
    control_profile = DEVICE_TYPE_FITNESS_EQUIPMENT

    def __init__(self, receiver, device) -> None:
        super().__init__(
            receiver,
            device,
            "fe_request_capabilities",
            "Request Capabilities",
            "mdi:information-outline",
        )

    async def async_press(self) -> None:
        # FE-C capabilities are Data Page 54 (0x36). Requesting it makes the
        # mode-specific HA controls capability-aware as soon as the trainer
        # responds, while retaining compatibility with trainers that do not.
        await async_send(
            self.receiver,
            self.ant_device_id,
            self.control_profile,
            request_data_page_payload(0x36),
        )


class AntPowerCalibrationButton(_AntDeviceControlButton):
    control_profile = DEVICE_TYPE_POWER

    def __init__(self, receiver, device) -> None:
        super().__init__(
            receiver, device, "power_manual_calibration", "Manual Calibration", "mdi:scale-balance"
        )

    async def async_press(self) -> None:
        await async_send(
            self.receiver,
            self.ant_device_id,
            self.control_profile,
            bicycle_power_manual_calibration_payload(),
        )
