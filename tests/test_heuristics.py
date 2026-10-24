"""Exact distances check the bounds independently of A*'s priorities."""

from collections import defaultdict, deque
from math import isfinite

import pytest

from bloxorz_solver.game.state import GameState, NormalBlock, SplitBlock
from bloxorz_solver.levels.loader import builtin_levels
from bloxorz_solver.solvers.astar import AStarSolver
from bloxorz_solver.solvers.heuristics import HEURISTICS, create_heuristic, resolve_heuristic
from bloxorz_solver.solvers.problem import BloxorzProblem
from bloxorz_solver.solvers.ucs import UCSSolver


def exact_distances(problem):
    reverse = defaultdict(list)
    seen = {problem.initial_state}
    queue = deque(seen)
    goals = []
    while queue:
        state = queue.popleft()
        if problem.is_goal(state):
            goals.append(state)
            continue
        for edge in problem.get_successors(state):
            reverse[edge.next_state].append(state)
            if edge.next_state not in seen:
                seen.add(edge.next_state)
                queue.append(edge.next_state)
        assert len(seen) < 50_000, "Use small exhaustive fixtures"
    distances = dict.fromkeys(goals, 0)
    queue = deque(goals)
    while queue:
        state = queue.popleft()
        for parent in reverse[state]:
            if parent not in distances:
                distances[parent] = distances[state] + 1
                queue.append(parent)
    return seen, distances


@pytest.mark.parametrize("level", builtin_levels(), ids=lambda level: level.id)
def test_builtins_are_admissible_on_every_reachable_state(level):
    problem = BloxorzProblem(level)
    states, distances = exact_distances(problem)
    assert problem.initial_state in distances
    for name in HEURISTICS:
        estimate = create_heuristic(name, problem)
        for state in states:
            value = estimate(state)
            assert isfinite(value) and value >= 0, (name, state)
            if state in distances:
                assert value <= distances[state] + 1e-10, (name, state, value, distances[state])
            if problem.is_goal(state):
                assert value == 0
        # Include current-position solving and both intact and split positions.
        starts = [problem.initial_state]
        for block_type in (NormalBlock, SplitBlock):
            starts.append(
                next(
                    (s for s in distances if isinstance(s.block, block_type) and distances[s] > 0),
                    problem.initial_state,
                )
            )
        for start in starts:
            path, _ = AStarSolver(problem, estimate)._search(start)
            assert path is not None and len(path) == distances[start]


def test_relaxed_board_improves_bound_and_has_no_cross_level_state():
    problems = [BloxorzProblem(level) for level in builtin_levels()]
    stronger = False
    for problem in problems:
        bound = create_heuristic("relaxed_board", problem)
        states, _ = exact_distances(problem)
        stronger |= any(bound(s) > problem.heuristic(s) for s in states)
    assert stronger
    first, second = problems[:2]
    a = create_heuristic("relaxed_board", first)
    original = a(first.initial_state)
    create_heuristic("relaxed_board", second)
    assert a(first.initial_state) == original


def test_zero_matches_unit_ucs_and_default_stays_compatible():
    problem = BloxorzProblem(builtin_levels()[0])
    assert AStarSolver(problem, create_heuristic("zero", problem))._search(
        problem.initial_state
    ) == UCSSolver(problem, cost_mode="unit")._search(problem.initial_state)
    assert AStarSolver(problem)._search(problem.initial_state) == AStarSolver(
        problem, create_heuristic("manhattan", problem)
    )._search(problem.initial_state)


def test_unreachable_goal_and_relaxed_lookup_fallback(make_level):
    problem = BloxorzProblem(make_level(grid=("S#G",), start=(0, 0), goal=(0, 2)))
    for name in HEURISTICS:
        bound = create_heuristic(name, problem)
        assert isfinite(bound(problem.initial_state))
        assert AStarSolver(problem, bound)._search(problem.initial_state)[0] is None
    bound = create_heuristic("relaxed_board", problem)
    unsupported = GameState(NormalBlock(0, 1))
    assert bound(unsupported) == problem.heuristic(unsupported)


@pytest.mark.parametrize(
    "name",
    ["unknown", "bad:", ":bad", "a:b:c", "no_such_heuristics:factory", "math:missing", "math:pi"],
)
def test_invalid_factory_names_have_clear_errors(name):
    with pytest.raises(ValueError, match="heuristic|Heuristic"):
        resolve_heuristic(name)


def test_importable_factory_and_invalid_factory_output():
    problem = BloxorzProblem(builtin_levels()[0])
    heuristic = create_heuristic("bloxorz_solver.solvers.heuristics:zero", problem)
    assert heuristic(problem.initial_state) == 0
    with pytest.raises(ValueError, match="must return a callable"):
        create_heuristic("builtins:str", problem)


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_astar_rejects_invalid_custom_estimates(value):
    problem = BloxorzProblem(builtin_levels()[0])
    with pytest.raises(ValueError, match="finite, nonnegative"):
        AStarSolver(problem, lambda state: value)._search(problem.initial_state)
