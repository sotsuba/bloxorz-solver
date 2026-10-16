"""Connect the Bloxorz rules to the solver protocol without a UI dependency."""

from collections.abc import Hashable, Iterable

from bloxorz_solver.game.rules import initial_state, is_goal, safe_transitions, support_failure
from bloxorz_solver.game.state import GameState, Level
from bloxorz_solver.game.validation import validate_level
from bloxorz_solver.solvers.contracts import Transition


class BloxorzProblem:
    """A level as a search graph; rolls and cube swaps each cost one action."""

    def __init__(self, level: Level):
        validate_level(level)
        self.level = level
        self.initial_state = initial_state(level)

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
