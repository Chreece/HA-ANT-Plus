"""Runtime diagnostics for HA ANT+ load investigations."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import logging
import os
import sys
import threading
import time
import traceback
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass
class AntPlusDiagnostics:
    """Thread-safe counters and timing samples for one ANT+ config entry."""

    started_monotonic: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    counters: Counter[str] = field(default_factory=Counter)
    profile_counters: Counter[str] = field(default_factory=Counter)
    timings: Counter[str] = field(default_factory=Counter)
    maxima: dict[str, float] = field(default_factory=dict)
    gauges: dict[str, Any] = field(default_factory=dict)
    _watchdog_stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _watchdog_thread: threading.Thread | None = field(default=None, repr=False)

    def start_watchdog(self) -> None:
        """Auto-dump stacks when remote ANT traffic coincides with one-core CPU saturation."""
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_run,
            name="antplus-diagnostics-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def stop(self) -> None:
        self._watchdog_stop.set()
        thread = self._watchdog_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _watchdog_run(self) -> None:
        last_wall = time.monotonic()
        last_cpu = time.process_time()
        last_remote = 0
        hot_samples = 0
        last_dump = 0.0
        while not self._watchdog_stop.wait(1.0):
            now_wall = time.monotonic()
            now_cpu = time.process_time()
            with self._lock:
                remote = int(self.counters.get("remote_packets_received", 0))
            wall_delta = max(now_wall - last_wall, 0.001)
            cpu_ratio = max(now_cpu - last_cpu, 0.0) / wall_delta
            remote_active = remote > last_remote
            self.set_gauge("process_cpu_core_ratio", round(cpu_ratio, 3))
            self.set_gauge("remote_packets_last_watchdog_interval", remote - last_remote)
            if remote_active and cpu_ratio >= 0.90:
                hot_samples += 1
            else:
                hot_samples = 0
            if hot_samples >= 2 and now_wall - last_dump >= 30.0:
                self.inc("automatic_hot_cpu_dumps")
                _LOGGER.warning(
                    "ANT+ DIAGNOSTICS automatic hot-CPU trigger: core_ratio=%.3f remote_packets_delta=%d",
                    cpu_ratio,
                    remote - last_remote,
                )
                log_diagnostics(self)
                last_dump = now_wall
                hot_samples = 0
            last_wall = now_wall
            last_cpu = now_cpu
            last_remote = remote

    def inc(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[key] += amount

    def inc_profile(self, key: str, device_type: int, amount: int = 1) -> None:
        with self._lock:
            self.profile_counters[f"{key}:{device_type}"] += amount

    def add_time(self, key: str, seconds: float) -> None:
        with self._lock:
            self.timings[key] += float(seconds)
            previous = self.maxima.get(key, 0.0)
            if seconds > previous:
                self.maxima[key] = float(seconds)

    def set_gauge(self, key: str, value: Any) -> None:
        with self._lock:
            self.gauges[key] = value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = max(time.monotonic() - self.started_monotonic, 0.001)
            counters = dict(self.counters)
            profile_counters = dict(self.profile_counters)
            timings = dict(self.timings)
            maxima = dict(self.maxima)
            gauges = dict(self.gauges)
        rates = {f"{key}_per_s": round(value / elapsed, 3) for key, value in counters.items()}
        return {
            "elapsed_s": round(elapsed, 3),
            "counters": counters,
            "rates": rates,
            "profiles": profile_counters,
            "timings_s": {key: round(value, 6) for key, value in timings.items()},
            "max_timing_s": {key: round(value, 6) for key, value in maxima.items()},
            "gauges": gauges,
        }

    def reset(self) -> None:
        with self._lock:
            self.started_monotonic = time.monotonic()
            self.counters.clear()
            self.profile_counters.clear()
            self.timings.clear()
            self.maxima.clear()
            self.gauges.clear()


def format_thread_stacks() -> str:
    """Return Python stacks for every current thread without using signals."""
    frames = sys._current_frames()
    threads = {thread.ident: thread for thread in threading.enumerate() if thread.ident is not None}
    sections: list[str] = []
    for ident, frame in frames.items():
        thread = threads.get(ident)
        name = thread.name if thread is not None else "unknown"
        daemon = thread.daemon if thread is not None else "?"
        header = f"--- thread name={name!r} ident={ident} daemon={daemon} ---"
        sections.append(header)
        sections.extend(line.rstrip("\n") for line in traceback.format_stack(frame))
    return "\n".join(sections)


def log_diagnostics(diagnostics: AntPlusDiagnostics) -> dict[str, Any]:
    """Log and return a runtime snapshot plus all Python thread stacks."""
    snapshot = diagnostics.snapshot()
    _LOGGER.warning("ANT+ DIAGNOSTICS SNAPSHOT: %s", snapshot)
    _LOGGER.warning(
        "ANT+ DIAGNOSTICS PROCESS: pid=%s active_threads=%s",
        os.getpid(),
        threading.active_count(),
    )
    _LOGGER.warning("ANT+ DIAGNOSTICS THREAD STACKS BEGIN\n%s\nANT+ DIAGNOSTICS THREAD STACKS END", format_thread_stacks())
    return snapshot
