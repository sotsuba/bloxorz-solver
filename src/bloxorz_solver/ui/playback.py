"""Reversible solution playback using complete, immutable session snapshots."""

from copy import copy
from dataclasses import dataclass
from threading import Event

from bloxorz_solver.game.session import GameSession, SessionStatus
from bloxorz_solver.game.state import Action, GameState, Outcome, TransitionResult
from bloxorz_solver.solvers.base import check_cancelled
from bloxorz_solver.ui.animation import BoardAnimation


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    state: GameState
    status: SessionStatus
    roll_count: int
    swap_count: int
    last_result: TransitionResult | None

    @classmethod
    def capture(cls, session: GameSession):
        return cls(session.state, session.status, session.roll_count,
                   session.swap_count, session.last_result)

    def restore(self, session: GameSession) -> None:
        session.state = self.state
        session.status = self.status
        session.roll_count = self.roll_count
        session.swap_count = self.swap_count
        session.last_result = self.last_result


def build_snapshots(session: GameSession, actions, cancel_event: Event | None = None):
    """Replay on a private session, never mutating the live UI's session."""
    replay = copy(session)
    snapshots = [SessionSnapshot.capture(replay)]
    for action in actions:
        check_cancelled(cancel_event)
        result = replay.apply_action(Action(action))
        if result is None or result.outcome in (Outcome.INVALID, Outcome.LOST):
            raise ValueError("Solver returned an invalid solution route")
        snapshots.append(SessionSnapshot.capture(replay))
    return tuple(snapshots)


class Playback:
    """Own progress and animation time; all seeking restores full game state."""

    def __init__(self, session: GameSession, animation: BoardAnimation, actions,
                 snapshots: tuple[SessionSnapshot, ...]):
        self.session = session
        self.animation = animation
        self.actions = tuple(actions)
        if len(snapshots) != len(self.actions) + 1:
            raise ValueError("Playback requires one snapshot per position")
        self.snapshots = snapshots
        self.index = 0
        self.playing = bool(self.actions)

    def _restore(self):
        self.snapshots[self.index].restore(self.session)
        self.animation.display(self.session.level, self.session.state,
                               won=self.session.status is SessionStatus.WON,
                               lost=self.session.status is SessionStatus.LOST)

    def play(self):
        if self.index == len(self.actions) and not self.animation.is_animating:
            self.index = 0
            self._restore()
        self.playing = bool(self.actions)

    def pause(self):
        self.playing = False

    def seek(self, index: int):
        self.pause()
        self.index = max(0, min(len(self.actions), int(index)))
        self._restore()

    def step(self, delta: int):
        self.seek(self.index + delta)

    def jump_to_start(self):
        self.seek(0)

    def jump_to_end(self):
        self.seek(len(self.actions))

    def _advance(self):
        previous = self.session.state
        self.index += 1
        self.snapshots[self.index].restore(self.session)
        action = self.actions[self.index - 1]
        result = self.session.last_result
        if action is Action.SWAP_ACTIVE_CUBE:
            self._restore()
        else:
            self.animation.animate_move(self.session.level, previous, action, result)

    def update(self, dt: float, speed: float):
        """Advance at most one action per frame, preserving visible roll animations."""
        if not self.playing:
            return
        self.animation.update(max(0, dt) * 1000 * speed)
        if not self.animation.is_animating:
            if self.index < len(self.actions):
                self._advance()
            else:
                self.playing = False
