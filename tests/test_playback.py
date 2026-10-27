"""Playback restores mechanisms and counters; workers stop cooperatively."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from bloxorz_solver.game.session import GameSession, SessionStatus
from bloxorz_solver.game.state import Action
from bloxorz_solver.levels.loader import builtin_levels
from bloxorz_solver.solvers.astar import AStarSolver
from bloxorz_solver.solvers.base import SearchCancelled
from bloxorz_solver.solvers.bfs import BFSSolver
from bloxorz_solver.solvers.contracts import Transition
from bloxorz_solver.solvers.dfs import DFSSolver
from bloxorz_solver.solvers.heuristics import create_heuristic
from bloxorz_solver.solvers.problem import BloxorzProblem
from bloxorz_solver.solvers.ucs import UCSSolver
from bloxorz_solver.ui.animation import BoardAnimation
from bloxorz_solver.ui.playback import Playback, SessionSnapshot, build_snapshots


def route_for(level, routes):
    actions = dict(U=Action.UP, L=Action.LEFT, D=Action.DOWN, R=Action.RIGHT,
                   X=Action.SWAP_ACTIVE_CUBE)
    return tuple(actions[letter] for letter in routes[level.id])


@pytest.mark.parametrize("stage", range(10))
def test_seek_restores_full_state_including_split_bridges_and_counters(stage, stage_routes):
    level = builtin_levels()[stage]
    session = GameSession(level)
    actions = route_for(level, stage_routes)
    snapshots = build_snapshots(session, actions)
    assert session.action_count == 0  # Snapshot construction leaves the source alone.
    animation = BoardAnimation(level, session.state)
    playback = Playback(session, animation, actions, snapshots)
    reference = GameSession(level)
    expected = [SessionSnapshot.capture(reference)]
    for action in actions:
        reference.apply_action(action)
        expected.append(SessionSnapshot.capture(reference))
    playback.update(0, 1)
    assert animation.is_animating
    playback.pause()
    elapsed = animation.elapsed_ms
    playback.update(10, 4)
    assert animation.elapsed_ms == elapsed
    for index in [len(actions), 0, *range(len(actions), -1, -1)]:
        playback.seek(index)
        assert SessionSnapshot.capture(session) == expected[index]
        assert not animation.is_animating and not playback.playing
        assert animation.block_hidden == (index == len(actions))
    playback.jump_to_end()
    assert session.status is SessionStatus.WON
    playback.play()  # Play from the end replays the full route.
    assert playback.index == 0 and session.action_count == 0
    for _ in range(len(actions) + 2):
        playback.update(10, 4)
    assert not playback.playing
    assert playback.index == len(actions)
    assert SessionSnapshot.capture(session) == expected[-1]
    playback.step(-1)
    assert SessionSnapshot.capture(session) == expected[-2]
    playback.step(1)
    assert SessionSnapshot.capture(session) == expected[-1]


def test_empty_route_and_seek_bounds(stage_routes):
    session = GameSession(builtin_levels()[0])
    for action in route_for(session.level, stage_routes):
        session.apply_action(action)
    animation = BoardAnimation(session.level, session.state)
    playback = Playback(session, animation, (), build_snapshots(session, ()))
    playback.update(0, 1)
    assert not playback.playing
    playback.seek(500)
    playback.step(-1)
    assert playback.index == 0 and session.status is SessionStatus.WON
    playback.play()
    assert not playback.playing


@pytest.mark.parametrize("solver_type", [BFSSolver, DFSSolver, UCSSolver, AStarSolver])
def test_running_solver_cancels_and_releases_worker_and_tracing(solver_type):
    started, cancel = Event(), Event()

    class EndlessProblem:
        def is_goal(self, state):
            return False

        def get_successors(self, state):
            started.set()
            yield Transition("next", state + 1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(solver_type(EndlessProblem()).solve, 0, cancel_event=cancel)
        assert started.wait(2)
        cancel.set()
        with pytest.raises(SearchCancelled):
            future.result(timeout=2)
        # The sole worker is available immediately after cancellation.
        assert executor.submit(lambda: "ready").result(timeout=2) == "ready"


def test_cancellation_during_relaxed_board_preprocessing():
    class CancelAfterChecks:
        checks = 0

        def is_set(self):
            self.checks += 1
            return self.checks >= 8

    event = CancelAfterChecks()
    problem = BloxorzProblem(builtin_levels()[5])
    with pytest.raises(SearchCancelled):
        create_heuristic("relaxed_board", problem, cancel_event=event)
    assert event.checks == 8
