from collections import deque
from typing import Hashable

from bloxorz_solver.solvers.base import BaseSolver


class BFSSolver(BaseSolver):
    """Breadth-First Search (BFS) solver implementation."""

    def _search(self, initial_state: Hashable) -> tuple[list[str] | None, int]:
        frontier = deque([initial_state])
        visited = {initial_state}
        parents = {}
        expanded = 0

        # BFS algorithm loop
        while frontier:
            state = frontier.popleft()
            if self.is_goal(state):
                return self.reconstruct_path(parents, state), expanded

            expanded += 1
            for transition in self.problem.get_successors(state):
                next_state = transition.next_state
                if next_state not in visited:
                    visited.add(next_state)
                    parents[next_state] = (state, transition.action)
                    frontier.append(next_state)

        return None, expanded
