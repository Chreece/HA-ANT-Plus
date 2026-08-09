"""OpenANT helpers for selecting one physical ANT USB adapter by serial."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import threading

import usb.core
import usb.util

from openant.base import ant as ant_module
from openant.base import driver as driver_module
from openant.base.driver import USB2Driver, USB3Driver
from openant.easy.node import Node

_LOGGER = logging.getLogger(__name__)
_NODE_CREATE_LOCK = threading.Lock()


def _usb_serial(device) -> str | None:
    try:
        if not device.iSerialNumber:
            return None
        value = usb.util.get_string(device, device.iSerialNumber)
    except Exception:
        return None
    if value is None:
        return None
    return str(value).rstrip("\x00").strip() or None


class _SerialSelectedMixin:
    """Override OpenANT's first-device USB lookup with serial selection."""

    TARGET_SERIAL: str | None = None

    def open(self) -> None:
        original_find = driver_module.usb.core.find
        serial = self.TARGET_SERIAL

        def selected_find(*args, **kwargs):
            id_vendor = kwargs.get("idVendor", self.ID_VENDOR)
            id_product = kwargs.get("idProduct", self.ID_PRODUCT)
            devices = original_find(
                idVendor=id_vendor,
                idProduct=id_product,
                find_all=True,
            )
            if devices is None:
                return None
            for device in devices:
                if serial is None or _usb_serial(device) == serial:
                    return device
            return None

        driver_module.usb.core.find = selected_find
        try:
            super().open()
        finally:
            driver_module.usb.core.find = original_find


class SerialUSB2Driver(_SerialSelectedMixin, USB2Driver):
    pass


class SerialUSB3Driver(_SerialSelectedMixin, USB3Driver):
    pass


@contextmanager
def _selected_openant_driver(vid: str, pid: str, serial: str | None):
    """Temporarily make Node() construct an Ant using our selected USB device."""
    pid_int = int(pid, 16)

    if pid_int == USB2Driver.ID_PRODUCT:
        driver_cls = SerialUSB2Driver
    elif pid_int == USB3Driver.ID_PRODUCT:
        driver_cls = SerialUSB3Driver
    else:
        raise ValueError(f"Unsupported ANT USB product {vid}:{pid}")

    class SelectedDriver(driver_cls):
        TARGET_SERIAL = serial

    original_find_driver = ant_module.find_driver
    ant_module.find_driver = lambda: SelectedDriver()
    try:
        yield
    finally:
        ant_module.find_driver = original_find_driver


def create_selected_node(
    vid: str,
    pid: str,
    serial: str | None,
) -> Node:
    """Create an OpenANT Node bound to one physical USB adapter."""
    with _NODE_CREATE_LOCK:
        with _selected_openant_driver(vid, pid, serial):
            return Node()
