"""Two parser adapters over the same ANT packet stream."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
import time

from .const import DEVICE_TYPE_NAMES
from .models import AntDevice, AntMetric
from .openant_bridge import OpenAntParserAdapter, supported_profile_types


class DecoderAdapter(Protocol):
    name: str

    def supports(self, device_type: int) -> bool:
        ...

    def feed(self, device: AntDevice, device_type: int, payload: bytes) -> list[AntMetric]:
        ...


class NativeAntPlusAdapter:
    """HA ANT+'s own native/documented parser backend."""

    name = "native_antplus"

    def supports(self, device_type: int) -> bool:
        return device_type in DEVICE_TYPE_NAMES

    def feed(self, device: AntDevice, device_type: int, payload: bytes) -> list[AntMetric]:
        from .decoder import decode_native_packet
        return decode_native_packet(device, device_type, payload)


class OpenAntAdapter:
    """Parser-only adapter around the decoders actually shipped by OpenANT."""

    name = "openant"

    def supports(self, device_type: int) -> bool:
        return device_type in supported_profile_types()

    def feed(self, device: AntDevice, device_type: int, payload: bytes) -> list[AntMetric]:
        if not self.supports(device_type):
            return []
        adapters = device.decoder_state.setdefault("openant_adapters", {})
        parser = adapters.get(device_type)
        if parser is None:
            try:
                parser = OpenAntParserAdapter(device_type, device.device_id)
            except Exception:
                parser = False
            adapters[device_type] = parser
        if not parser:
            return []
        diagnostics = device.decoder_state.get("_diagnostics")
        started = time.perf_counter()
        metrics = parser.feed(payload)
        elapsed = time.perf_counter() - started
        if diagnostics is not None:
            diagnostics.inc("openant_calls")
            diagnostics.inc_profile("openant_calls", device_type)
            diagnostics.inc("openant_metrics", len(metrics))
            diagnostics.add_time("openant_total", elapsed)
        return metrics


DECODER_ADAPTERS: tuple[DecoderAdapter, ...] = (
    NativeAntPlusAdapter(),
    OpenAntAdapter(),
)


def decode_with_adapters(
    device: AntDevice,
    device_type: int,
    payload: bytes,
    adapters: Iterable[DecoderAdapter] = DECODER_ADAPTERS,
) -> list[AntMetric]:
    """Run native first, then let OpenANT fill missing metric keys."""
    merged: dict[str, AntMetric] = {}
    sources: dict[str, str] = {}

    active_backends = []
    for adapter in adapters:
        if not adapter.supports(device_type):
            continue
        active_backends.append(adapter.name)
        for metric in adapter.feed(device, device_type, payload):
            if metric.key in merged:
                continue
            merged[metric.key] = metric
            sources[metric.key] = adapter.name

    device.decoder_state["metric_decoder_sources"] = sources
    device.decoder_state["decoder_backends"] = active_backends
    return list(merged.values())


def decoder_backend_rows() -> list[dict[str, object]]:
    from .profile_support import native_profile_types

    return [
        {
            "name": "native_antplus",
            "recognized_profiles": sorted(DEVICE_TYPE_NAMES),
            "semantic_profiles": sorted(native_profile_types()),
            "raw_diagnostics": True,
            "common_pages": True,
        },
        {
            "name": "openant",
            "recognized_profiles": sorted(supported_profile_types()),
            "semantic_profiles": sorted(supported_profile_types()),
            "raw_diagnostics": False,
            "common_pages": False,
        },
    ]
