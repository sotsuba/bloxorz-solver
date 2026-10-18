"""Connect the Bloxorz rules to the solver protocol without a UI dependency."""

from collections.abc import Hashable, Iterable

from bloxorz_solver.game.rules import (
    initial_state,
    is_goal,
    occupied_cells,
    safe_transitions,
    support_failure,
)
from bloxorz_solver.game.state import GameState, Level, SwitchKind
from bloxorz_solver.game.validation import validate_level
from bloxorz_solver.solvers.contracts import Transition


class BloxorzProblem:
    """A level as a search graph; rolls and cube swaps each cost one action."""

    def __init__(self, level: Level):
        validate_level(level)
        self.level = level
        self.initial_state = initial_state(level)
        self._heuristic_targets = (level.goal,) + tuple(
            switch.position for switch in level.switches if switch.kind is SwitchKind.SPLIT
        )

    def heuristic(self, state: Hashable) -> float:
        """Lower bound on unit-cost actions to the goal or the next split.

        Count both cubes, including the two stacked at a standing position.
        A roll reduces their summed distance to the nearest targets by at most
        three; a split-cube move reduces it by at most one. Immediately before
        a split teleport, the sum is at most three because its switch is a
        target. Thus the rounded bound is consistent even across teleports.
        Ignore terrain, bridges, swaps, and the required goal orientation.
        """
        if not isinstance(state, GameState):
            raise TypeError("BloxorzProblem expects a GameState")
        cells = occupied_cells(state.block)
        if len(cells) == 1:
            cells = cells * 2
        distance = sum(
            min(
                abs(cell.row - target.row) + abs(cell.col - target.col)
                for target in self._heuristic_targets
            )
            for cell in cells
        )
        return (distance + 2) // 3

    def is_goal(self, state: Hashable) -> bool:
        return (
            isinstance(state, GameState)
            and not support_failure(self.level, state)
            and is_goal(self.level, state)
        )

    def get_successors(self, state: Hashable) -> Iterable[Transition]:
        if not isinstance(state, GameState):
            raise TypeError("BloxorzProblem expects a GameState")
        for action, result in safe_transitions(self.level, state):
            yield Transition(action.value, result.next_state)
