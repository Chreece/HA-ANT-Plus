"""OpenANT helpers for selecting one physical ANT USB adapter by bus/address."""

from __future__ import annotations

from contextlib import contextmanager
import threading

from openant.base import ant as ant_module
from openant.base import driver as driver_module
from openant.base.driver import USB2Driver, USB3Driver
from openant.easy.node import Node

_NODE_CREATE_LOCK = threading.Lock()


class _PhysicalSelectedMixin:
    """Override OpenANT's first-match lookup with Linux bus/address selection."""

    TARGET_BUS: int | None = None
    TARGET_ADDRESS: int | None = None

    def open(self) -> None:
        original_find = driver_module.usb.core.find
        target_bus = self.TARGET_BUS
        target_address = self.TARGET_ADDRESS

        def selected_find(*args, **kwargs):
            devices = original_find(
                idVendor=kwargs.get("idVendor", self.ID_VENDOR),
                idProduct=kwargs.get("idProduct", self.ID_PRODUCT),
                find_all=True,
            )
            if devices is None:
                return None

            for device in devices:
                if (
                    getattr(device, "bus", None) == target_bus
                    and getattr(device, "address", None) == target_address
                ):
                    return device

            return None

        driver_module.usb.core.find = selected_find
        try:
            super().open()
        finally:
            driver_module.usb.core.find = original_find


class PhysicalUSB2Driver(_PhysicalSelectedMixin, USB2Driver):
    pass


class PhysicalUSB3Driver(_PhysicalSelectedMixin, USB3Driver):
    pass


@contextmanager
def _selected_openant_driver(
    pid: str,
    bus: int,
    address: int,
):
    pid_int = int(pid, 16)

    if pid_int == USB2Driver.ID_PRODUCT:
        driver_cls = PhysicalUSB2Driver
    elif pid_int == USB3Driver.ID_PRODUCT:
        driver_cls = PhysicalUSB3Driver
    else:
        raise ValueError(f"Unsupported ANT USB product id {pid}")

    class SelectedDriver(driver_cls):
        TARGET_BUS = bus
        TARGET_ADDRESS = address

    original_find_driver = ant_module.find_driver
    ant_module.find_driver = lambda: SelectedDriver()
    try:
        yield
    finally:
        ant_module.find_driver = original_find_driver


def create_selected_node(
    pid: str,
    bus: int,
    address: int,
) -> Node:
    """Create an OpenANT Node bound to one exact physical Linux USB device."""
    with _NODE_CREATE_LOCK:
        with _selected_openant_driver(pid, bus, address):
            return Node()
