"""The migrated rules plug into the existing search contract and solver base."""

from collections import deque

import pytest

from bloxorz_solver.game.rules import transition
from bloxorz_solver.game.state import Action, GameState, NormalBlock, Outcome
from bloxorz_solver.levels.loader import builtin_levels
from bloxorz_solver.solvers.base import BaseSolver
from bloxorz_solver.solvers.problem import BloxorzProblem


class BreadthFirstProbe(BaseSolver):
    """Small test consumer of the public contract, not a production algorithm."""

    def _search(self, initial_state):
        queue, seen, parents = deque([initial_state]), {initial_state}, {}
        expanded = 0
        while queue:
            state = queue.popleft()
            if self.is_goal(state):
                return self.reconstruct_path(parents, state), expanded
            expanded += 1
            for edge in self.problem.get_successors(state):
                if edge.next_state not in seen:
                    seen.add(edge.next_state)
                    parents[edge.next_state] = state, edge.action
                    queue.append(edge.next_state)
        return None, expanded


def test_existing_solver_base_can_solve_migrated_game():
    problem = BloxorzProblem(builtin_levels()[0])
    result = BreadthFirstProbe(problem).solve(problem.initial_state)
    assert result.is_found
    assert result.path == ["right"] * 4
    assert result.solution_length == 4
    assert result.expanded_nodes > 0
    assert result.peak_memory > 0
    state = problem.initial_state
    for action in result.path:
        state = transition(problem.level, state, Action(action)).next_state
    assert problem.is_goal(state)
    assert list(problem.get_successors(state)) == []


def test_successors_exclude_loss_and_invalid_actions():
    problem = BloxorzProblem(builtin_levels()[0])
    for edge in problem.get_successors(problem.initial_state):
        result = transition(problem.level, problem.initial_state, Action(edge.action))
        assert result.outcome in (Outcome.MOVED, Outcome.WON)
        assert result.next_state == edge.next_state
        assert edge.cost == 1
    lost = GameState(NormalBlock(-1, -1))
    assert list(problem.get_successors(lost)) == []
    assert not problem.is_goal(lost)
    with pytest.raises(TypeError):
        list(problem.get_successors("invalid"))


def test_campaign_routes_are_representable_by_search_edges(stage_routes):
    actions = dict(U="up", D="down", L="left", R="right", X="swap")
    for level in builtin_levels():
        problem = BloxorzProblem(level)
        state = problem.initial_state
        for letter in stage_routes[level.id]:
            edges = {edge.action: edge for edge in problem.get_successors(state)}
            state = edges[actions[letter]].next_state
        assert problem.is_goal(state)
