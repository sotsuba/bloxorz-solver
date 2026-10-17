"""A* graph search with best-cost tracking and reopening of improved states."""

from collections.abc import Callable, Hashable
from heapq import heappop, heappush
from itertools import count
from math import inf, isfinite

from bloxorz_solver.solvers.base import BaseSolver
from bloxorz_solver.solvers.contracts import SearchProblem


class AStarSolver(BaseSolver):
    """Find a minimum-cost path using an admissible, nonnegative heuristic.

    Use the supplied callable, or the problem's ``heuristic(state)`` method.
    Without either, a zero heuristic gives uniform-cost search. Heuristics must
    be zero at goals and never overestimate the remaining cost. Inconsistent
    heuristics are supported by reopening states when their cost improves.
    """

    def __init__(
        self,
        problem: SearchProblem,
        heuristic: Callable[[Hashable], float] | None = None,
    ):
        super().__init__(problem)
        self.heuristic = (
            heuristic if heuristic is not None else getattr(problem, "heuristic", lambda state: 0.0)
        )

    def _estimate(self, state: Hashable) -> float:
        estimate = self.heuristic(state)
        if not isfinite(estimate) or estimate < 0:
            raise ValueError("A* requires finite, nonnegative heuristic values")
        return estimate

    def _search(self, initial_state: Hashable) -> tuple[list[str] | None, int]:
        # The counter breaks ties without comparing arbitrary hashable states.
        order = count()
        frontier = [(self._estimate(initial_state), next(order), 0.0, initial_state)]
        best_cost = {initial_state: 0.0}
        parents = {}
        expanded = 0

        while frontier:
            _, _, cost, state = heappop(frontier)
            if cost != best_cost[state]:
                continue
            if self.is_goal(state):
                return self.reconstruct_path(parents, state), expanded

            expanded += 1
            for edge in self.problem.get_successors(state):
                if not isfinite(edge.cost) or edge.cost < 0:
                    raise ValueError("A* requires finite, nonnegative transition costs")
                next_cost = cost + edge.cost
                if next_cost >= best_cost.get(edge.next_state, inf):
                    continue
                priority = next_cost + self._estimate(edge.next_state)
                best_cost[edge.next_state] = next_cost
                parents[edge.next_state] = state, edge.action
                heappush(frontier, (priority, next(order), next_cost, edge.next_state))

        return None, expanded
