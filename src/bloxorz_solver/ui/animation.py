"""Elapsed-time animation state, independent of the Pygame renderer and clock."""

from dataclasses import dataclass
from math import cos, pi

from bloxorz_solver.game.rules import bridge_is_open, supported_cells
from bloxorz_solver.game.state import (
    Action,
    EventType,
    GameState,
    Level,
    Outcome,
    Position,
    TransitionResult,
)
from bloxorz_solver.ui.motion import Mesh, block_meshes, drop_meshes, fall_meshes, roll_meshes

ROLL_MS, TRANSFORM_MS, BRIDGE_MS, FALL_MS = 230, 180, 300, 540


@dataclass(frozen=True)
class _MoveAnimation:
    """Complete context and shared timeline for a single committed movement."""

    previous: GameState
    action: Action
    result: TransitionResult
    fall_support: tuple[Position, ...]
    transform_ms: int
    bridge_ms: int
    fall_ms: int

    @property
    def transform_start_ms(self) -> int:
        return ROLL_MS

    @property
    def bridge_start_ms(self) -> int:
        return self.transform_start_ms + self.transform_ms

    @property
    def fall_start_ms(self) -> int:
        return self.bridge_start_ms + self.bridge_ms

    @property
    def duration_ms(self) -> int:
        return self.fall_start_ms + self.fall_ms


class BoardAnimation:
    """Animate a committed game result without changing its state or rules."""

    def __init__(self, level: Level, state: GameState):
        self.display(level, state)

    def display(
        self, level: Level, state: GameState, *, lost: bool = False, won: bool = False
    ) -> None:
        self.cancel_animation()
        self.level, self.state = level, state
        self.block_hidden = lost or won

    def cancel_animation(self) -> None:
        self._move: _MoveAnimation | None = None
        self.elapsed_ms = 0.0

    @property
    def is_animating(self) -> bool:
        return self._move is not None

    @property
    def duration_ms(self) -> int:
        return self._move.duration_ms if self._move else ROLL_MS

    @property
    def fall_support(self) -> tuple[Position, ...]:
        return self._move.fall_support if self._move else ()

    @property
    def phase(self) -> str:
        move = self._move
        if move is None:
            return ""
        if self.elapsed_ms < move.transform_start_ms:
            return "roll"
        if self.elapsed_ms < move.bridge_start_ms:
            return "transform"
        if self.elapsed_ms < move.fall_start_ms:
            return "bridge"
        return "fall"

    @property
    def falling_outcome(self) -> Outcome | None:
        return self._move.result.outcome if self._move and self.phase == "fall" else None

    def animate_move(
        self, level: Level, previous: GameState, action: Action, result: TransitionResult
    ) -> None:
        self.display(level, result.next_state)
        transforms = any(
            event.kind in (EventType.BLOCK_SPLIT, EventType.BLOCK_MERGED) for event in result.events
        )
        self._move = _MoveAnimation(
            previous=previous,
            action=action,
            result=result,
            fall_support=(
                supported_cells(level, result.next_state) if result.outcome is Outcome.LOST else ()
            ),
            transform_ms=TRANSFORM_MS if transforms else 0,
            bridge_ms=BRIDGE_MS if previous.bridge_mask != result.next_state.bridge_mask else 0,
            fall_ms=FALL_MS if result.outcome in (Outcome.WON, Outcome.LOST) else 0,
        )

    def update(self, elapsed_ms: float) -> None:
        if self._move is not None:
            self.elapsed_ms += max(0, elapsed_ms)
            if self.elapsed_ms >= self.duration_ms:
                self.block_hidden = self._move.result.outcome in (Outcome.WON, Outcome.LOST)
                self.cancel_animation()

    def _fraction(self, start_ms: int, duration_ms: int) -> float:
        return (
            max(0.0, min(1.0, (self.elapsed_ms - start_ms) / duration_ms)) if duration_ms else 1.0
        )

    @staticmethod
    def _ease(progress: float) -> float:
        return (1 - cos(pi * progress)) / 2

    def bridge_openness(self, bridge_id: str) -> float:
        target = float(bridge_is_open(self.level, self.state, bridge_id))
        move = self._move
        if move is None:
            return target
        previous = float(bridge_is_open(self.level, move.previous, bridge_id))
        progress = self._ease(self._fraction(move.bridge_start_ms, move.bridge_ms))
        return previous + (target - previous) * progress

    def frame_meshes(self) -> tuple[tuple[Mesh, float], ...]:
        """Select rigid rolling, split/merge fading, or accelerated falling geometry."""
        move = self._move
        if move is None:
            return tuple((mesh, 1.0) for mesh in block_meshes(self.state.block))
        if self.elapsed_ms < move.transform_start_ms:
            meshes = roll_meshes(
                move.previous.block, move.action, self._ease(self._fraction(0, ROLL_MS))
            )
            return tuple((mesh, 1.0) for mesh in meshes)
        final = block_meshes(self.state.block)
        transform = self._fraction(move.transform_start_ms, move.transform_ms)
        if move.transform_ms and transform < 1:
            source = roll_meshes(move.previous.block, move.action, 1)
            return tuple((mesh, 1 - transform) for mesh in source) + tuple(
                (mesh, transform) for mesh in final
            )
        if move.fall_ms:
            progress = self._fraction(move.fall_start_ms, move.fall_ms)
            lost = move.result.outcome is Outcome.LOST
            meshes = (
                fall_meshes(self.state.block, self.fall_support, progress, tumble=move.action)
                if lost
                else drop_meshes(final, progress)
            )
            opacity = min(1.0, 2 * (1 - progress)) if lost else 1.0
            return tuple((mesh, opacity) for mesh in meshes)
        return tuple((mesh, 1.0) for mesh in final)
