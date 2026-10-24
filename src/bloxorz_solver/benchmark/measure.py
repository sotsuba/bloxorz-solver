"""Benchmark-only adapter; production solver classes and metrics are untouched.

The protected _search hook is the existing common algorithm contract. Keep its
use isolated here and test adapter equivalence to the public solve method.
"""

import time
import tracemalloc
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Literal

from bloxorz_solver.solvers.base import BaseSolver


@dataclass(frozen=True)
class Measurement:
    path: list[str] | None
    expanded_nodes: int
    search_time: float | None
    peak_memory: int | None
    initialization_time: float | None = None
    total_time: float | None = None

    @property
    def is_found(self) -> bool:
        return self.path is not None

    @property
    def solution_length(self) -> int | None:
        return len(self.path) if self.path is not None else None


def measure_search(
    solver: BaseSolver, initial_state: Hashable, *, mode: Literal["timing", "memory"] = "timing"
) -> Measurement:
    """Measure only algorithm execution in a clean, isolated worker.

    Refuse an existing tracer instead of disturbing caller-owned instrumentation.
    Memory passes deliberately do not provide comparable timing measurements.
    """
    if mode not in ("timing", "memory"):
        raise ValueError("mode must be timing or memory")
    if tracemalloc.is_tracing():
        raise RuntimeError("Benchmark measurement requires a fresh, untraced process")
    if mode == "timing":
        started = time.perf_counter()
        path, expanded = solver._search(initial_state)
        return Measurement(path, expanded, time.perf_counter() - started, None)
    tracemalloc.start()
    try:
        path, expanded = solver._search(initial_state)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return Measurement(path, expanded, None, peak)


def measure_solver(
    factory: Callable[[], BaseSolver], initial_state: Hashable, *, mode="timing"
) -> Measurement:
    """Include solver/heuristic construction, keeping search-only time separate.

    In memory mode the trace includes tables retained by heuristic factories.
    The caller enforces one resource/time budget over construction and search.
    """
    if mode not in ("timing", "memory"):
        raise ValueError("mode must be timing or memory")
    if tracemalloc.is_tracing():
        raise RuntimeError("Benchmark measurement requires a fresh, untraced process")
    if mode == "timing":
        started = time.perf_counter()
        solver = factory()
        initialized = time.perf_counter()
        path, expanded = solver._search(initial_state)
        finished = time.perf_counter()
        return Measurement(
            path, expanded, finished - initialized, None, initialized - started, finished - started
        )
    tracemalloc.start()
    try:
        solver = factory()
        path, expanded = solver._search(initial_state)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return Measurement(path, expanded, None, peak)
