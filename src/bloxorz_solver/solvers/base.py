from abc import ABC, abstractmethod 
from dataclasses import dataclass 
from typing import Hashable 
from bloxorz_solver.solvers.contracts import SearchProblem
import time
import tracemalloc

@dataclass 
class SearchResult:
    """Stores the solution path and search performance metrics."""

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

    def solve(self, initial_state: Hashable) -> SearchResult:
        """Run the search and collect time, memory, and node metrics."""
        tracemalloc.start()
        start_time = time.perf_counter()

        try:
            path, expanded = self._search(initial_state)
            elapsed = time.perf_counter() - start_time 
            _, peak = tracemalloc.get_traced_memory() 
        finally:
            tracemalloc.stop()

        return SearchResult(
            path=path,
            search_time=elapsed,
            peak_memory=peak,
            expanded_nodes=expanded,
            solution_length=len(path) if path is not None else 0
        )
 
    @abstractmethod
    def _search(self, initial_state: Hashable) -> tuple[list[str] | None, int]:
        """
        Search for a path from the initial state to the goal.

        Returns:
            A tuple of (solution path or None, number of expanded nodes).
        """
        pass 

    def is_goal(self, state: Hashable) -> bool:
        return self.problem.is_goal(state)

    @staticmethod
    def reconstruct_path(parents: dict, goal_state: Hashable) -> list[str]:
        """Reconstruct the action sequence from parent references."""
        path = [] 
        current = goal_state

        while current in parents:
            previous, action = parents[current]
            path.append(action)
            current = previous

        return path[::-1]

