import time
import tracemalloc
from abc import ABC, abstractmethod
from collections.abc import Hashable
from dataclasses import dataclass
from threading import Event

from bloxorz_solver.solvers.contracts import SearchProblem


class SearchCancelled(Exception):
    """Cooperative cancellation, distinct from an exhausted search."""


def check_cancelled(event: Event | None) -> None:
    if event is not None and event.is_set():
        raise SearchCancelled()


@dataclass
class SearchResult:
    """Stores search metrics; peak_memory is bytes in the active tracing session."""

    path: list[str] | None
    search_time: float
    peak_memory: int
    expanded_nodes: int
    solution_length: int

    @property
    def is_found(self) -> bool:
        return self.path is not None


class BaseSolver(ABC):
    """Abstract base class for BFS, DFS, UCS, and A* solvers."""

    def __init__(self, problem: SearchProblem):
        self.problem = problem
        self._cancel_event: Event | None = None

    def solve(self, initial_state: Hashable, *, cancel_event: Event | None = None) -> SearchResult:
        """Collect metrics, preserving tracing started by the caller.

        With existing tracing, peak_memory includes that session's earlier peak.
        """
        self._cancel_event = cancel_event
        self.check_cancelled()
        owns_tracing = not tracemalloc.is_tracing()
        if owns_tracing:
            tracemalloc.start()
        start_time = time.perf_counter()

        try:
            path, expanded = self._search(initial_state)
            self.check_cancelled()
            elapsed = time.perf_counter() - start_time
            _, peak = tracemalloc.get_traced_memory()
        finally:
            if owns_tracing:
                tracemalloc.stop()

        return SearchResult(
            path=path,
            search_time=elapsed,
            peak_memory=peak,
            expanded_nodes=expanded,
            solution_length=len(path) if path is not None else 0,
        )

    @abstractmethod
    def _search(self, initial_state: Hashable) -> tuple[list[str] | None, int]:
        """
        Search for a path from the initial state to the goal.

        Returns:
            A tuple of (solution path or None, number of expanded nodes).
        """
        pass

    def check_cancelled(self) -> None:
        check_cancelled(self._cancel_event)

    def is_goal(self, state: Hashable) -> bool:
        return self.problem.is_goal(state)

    @staticmethod
    def reconstruct_path(parents: dict, goal_state: Hashable, *,
                         cancel_event: Event | None = None) -> list[str]:
        """Reconstruct the action sequence from parent references."""
        path = []
        current = goal_state

        while current in parents:
            check_cancelled(cancel_event)
            previous, action = parents[current]
            path.append(action)
            current = previous

        return path[::-1]
