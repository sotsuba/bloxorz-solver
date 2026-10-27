"""Uniform-cost search with optional Combined C costs for Bloxorz levels."""

import heapq
from collections.abc import Hashable
from itertools import count
from math import isfinite
from typing import Literal

from bloxorz_solver.game.rules import occupied_cells
from bloxorz_solver.game.state import Action, GameState
from bloxorz_solver.solvers.base import BaseSolver
from bloxorz_solver.solvers.contracts import SearchProblem, Transition
from bloxorz_solver.solvers.problem import BloxorzProblem


class UCSSolver(BaseSolver):
    """Find a minimum-cost path using nonnegative transition costs.

    On Bloxorz levels, the default Combined C cost adds 2 for switching the
    active cube and 1 for a directional move ending on fragile terrain.
    Set ``cost_mode="unit"`` to use the original problem's transition costs.
    On other SearchProblem implementations, transition costs are used as-is.
    """

    def __init__(
        self,
        problem: SearchProblem,
        *,
        cost_mode: Literal["combined", "unit"] = "combined",
    ) -> None:
        super().__init__(problem)
        if cost_mode not in ("combined", "unit"):
            raise ValueError("cost_mode must be 'combined' or 'unit'")
        self.cost_mode = cost_mode

    def _transition_cost(self, edge: Transition) -> float:
        """Add Combined C penalties without changing the game's state graph."""
        if self.cost_mode == "unit" or not isinstance(self.problem, BloxorzProblem):
            return edge.cost
        if edge.action == Action.SWAP_ACTIVE_CUBE.value:
            return edge.cost + 2.0
        next_state = edge.next_state
        if not isinstance(next_state, GameState):
            raise TypeError("Bloxorz successors must contain GameState values")
        exposed = any(
            self.problem.level.grid[cell.row][cell.col] == "F"
            for cell in occupied_cells(next_state.block)
        )
        return edge.cost + float(exposed)

    def _search(self, initial_state: Hashable) -> tuple[list[str] | None, int]:
        sequence = count()
        frontier = [(0, next(sequence), initial_state)]
        best_cost = {initial_state: 0}
        parents = {}
        expanded = 0

        while frontier:
            self.check_cancelled()
            current_cost, _, state = heapq.heappop(frontier)
            # A cheaper route may have replaced this entry since it was queued.
            if current_cost != best_cost[state]:
                continue
            if self.is_goal(state):
                return self.reconstruct_path(parents, state, cancel_event=self._cancel_event), expanded

            expanded += 1
            for transition in self.problem.get_successors(state):
                self.check_cancelled()
                if not isfinite(transition.cost) or transition.cost < 0:
                    raise ValueError("UCS requires finite, nonnegative transition costs")
                edge_cost = self._transition_cost(transition)
                if not isfinite(edge_cost) or edge_cost < 0:
                    raise ValueError("UCS requires finite, nonnegative transition costs")
                new_cost = current_cost + edge_cost
                successor = transition.next_state
                previous_cost = best_cost.get(successor)
                if previous_cost is None or new_cost < previous_cost:
                    best_cost[successor] = new_cost
                    parents[successor] = state, transition.action
                    heapq.heappush(frontier, (new_cost, next(sequence), successor))

        return None, expanded
