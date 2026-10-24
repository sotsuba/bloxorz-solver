"""Level-local admissible heuristics and importable factories for unit-cost Bloxorz.

Factories may preprocess the problem, then return a state -> estimate callable.
Custom factories must return finite nonnegative lower bounds, zero at goals.
"""

from collections import defaultdict, deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from importlib import import_module
from math import hypot

from bloxorz_solver.game.rules import ROLL_TABLE, occupied_cells
from bloxorz_solver.game.state import GameState, NormalBlock, Orientation, SwitchKind
from bloxorz_solver.solvers.problem import BloxorzProblem

Heuristic = Callable[[Hashable], float]
HeuristicFactory = Callable[[BloxorzProblem], Heuristic]


def _state(state: Hashable) -> GameState:
    if not isinstance(state, GameState):
        raise TypeError("Bloxorz heuristics expect a GameState")
    return state


def zero(problem: BloxorzProblem) -> Heuristic:
    """Uniform-cost search baseline."""
    return lambda state: 0.0


def manhattan(problem: BloxorzProblem) -> Heuristic:
    """Existing rounded cube-distance bound, including split-switch targets."""
    return problem.heuristic


def euclidean(problem: BloxorzProblem) -> Heuristic:
    """Unrounded Euclidean analogue of the existing split-aware distance bound."""
    targets = (problem.level.goal,) + tuple(
        switch.position for switch in problem.level.switches if switch.kind is SwitchKind.SPLIT
    )

    def estimate(state: Hashable) -> float:
        cells = occupied_cells(_state(state).block)
        if len(cells) == 1:
            cells *= 2
        return (
            sum(min(hypot(cell.row - p.row, cell.col - p.col) for p in targets) for cell in cells)
            / 3
        )

    return estimate


def relaxed_board(problem: BloxorzProblem) -> Heuristic:
    """Reverse roll distances with open bridges and unbreakable fragile floor.

    Until the first split, every real roll is an edge in this relaxed graph.
    Reaching any standing split switch is accepted as a terminal, so its distance
    never exceeds the real cost to the first split or goal. Split states use the
    existing bound. The maximum of two admissible bounds remains admissible;
    consistency across split/merge transitions is not required by our A*.
    """
    level = problem.level
    floor = {
        (row, col)
        for row, line in enumerate(level.grid)
        for col, tile in enumerate(line)
        if tile != "#"
    } | set(level.bridge_at)
    poses = set()
    for row, col in floor:
        for orientation in Orientation:
            block = NormalBlock(row, col, orientation)
            if all(cell in floor for cell in occupied_cells(block)):
                poses.add(block)
    reverse = defaultdict(list)
    for block in poses:
        for dr, dc, orientation in ROLL_TABLE[block.orientation].values():
            successor = NormalBlock(block.row + dr, block.col + dc, orientation)
            if successor in poses:
                reverse[successor].append(block)
    targets = (level.goal,) + tuple(
        switch.position for switch in level.switches if switch.kind is SwitchKind.SPLIT
    )
    distances = {NormalBlock(p.row, p.col): 0 for p in targets}
    queue = deque(distances)
    while queue:
        current = queue.popleft()
        for previous in reverse[current]:
            if previous not in distances:
                distances[previous] = distances[current] + 1
                queue.append(previous)

    def estimate(state: Hashable) -> float:
        state = _state(state)
        return max(problem.heuristic(state), distances.get(state.block, 0))

    return estimate


@dataclass(frozen=True)
class HeuristicDefinition:
    name: str
    label: str
    description: str
    factory: HeuristicFactory


HEURISTICS = {
    definition.name: definition
    for definition in (
        HeuristicDefinition("zero", "Zero", "Uniform-cost baseline", zero),
        HeuristicDefinition(
            "manhattan", "Manhattan", "Split-aware rounded cube distances", manhattan
        ),
        HeuristicDefinition(
            "euclidean", "Euclidean", "Split-aware Euclidean cube distances", euclidean
        ),
        HeuristicDefinition(
            "relaxed_board", "Relaxed board", "Precomputed relaxed roll distances", relaxed_board
        ),
    )
}
DEFAULT_HEURISTIC = "manhattan"


def resolve_heuristic(name: str) -> HeuristicFactory:
    """Resolve a built-in name or a trusted ``module:function`` factory."""
    if name in HEURISTICS:
        return HEURISTICS[name].factory
    module, separator, attribute = name.partition(":")
    if not separator or not module or not attribute or ":" in attribute:
        raise ValueError(
            f"Unknown heuristic {name!r}; use {', '.join(HEURISTICS)} or module:function"
        )
    try:
        factory = getattr(import_module(module), attribute)
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"Cannot load heuristic factory {name!r}: {exc}") from exc
    if not callable(factory):
        raise ValueError(f"Heuristic factory {name!r} is not callable")
    return factory


def create_heuristic(name: str, problem: BloxorzProblem) -> Heuristic:
    heuristic = resolve_heuristic(name)(problem)
    if not callable(heuristic):
        raise ValueError(f"Heuristic factory {name!r} must return a callable")
    return heuristic
