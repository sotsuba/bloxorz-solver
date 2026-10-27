from collections.abc import Hashable

from bloxorz_solver.solvers.base import BaseSolver


class DFSSolver(BaseSolver):
    """Depth-First Search (DFS) solver implementation.

    Iterative, so deep levels cannot hit Python's recursion limit. The action path
    is kept on a stack and trimmed when backtracking, which removes the need for a
    parent map. The solution found is valid but not necessarily the shortest.
    """

    def _search(self, initial_state: Hashable) -> tuple[list[str] | None, int]:
        if self.is_goal(initial_state):
            return [], 0

        visited = {initial_state}
        path: list[str] = []  # actions from the initial state to the current state
        # iterators[i] yields the successors of the state reached after path[:i].
        # Successors are produced lazily, so each state is only expanded as far as
        # the search actually needs.
        iterators = [iter(self.problem.get_successors(initial_state))]
        expanded = 1

        while iterators:
            self.check_cancelled()
            for transition in iterators[-1]:
                self.check_cancelled()
                next_state = transition.next_state
                if next_state in visited:
                    continue

                visited.add(next_state)
                path.append(transition.action)
                if self.is_goal(next_state):
                    return path, expanded

                expanded += 1
                iterators.append(iter(self.problem.get_successors(next_state)))
                break  # descend into the new state immediately
            else:
                # Every successor has been tried: backtrack one level.
                iterators.pop()
                if path:
                    path.pop()

        return None, expanded
