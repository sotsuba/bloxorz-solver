"""Animation timing can be driven without initializing a display or event loop."""

import pytest

from bloxorz_solver.game.rules import initial_state, transition
from bloxorz_solver.game.state import (
    Action,
    Bridge,
    BridgeEffect,
    EffectMode,
    GameState,
    NormalBlock,
    Orientation,
    Outcome,
    Position,
    Switch,
    SwitchKind,
)
from bloxorz_solver.levels.loader import builtin_levels
from bloxorz_solver.ui.animation import BRIDGE_MS, FALL_MS, ROLL_MS, TRANSFORM_MS, BoardAnimation
from bloxorz_solver.ui.motion import block_meshes


def test_animation_can_be_advanced_and_cancelled_without_pygame():
    level = builtin_levels()[0]
    state = initial_state(level)
    animation = BoardAnimation(level, state)
    result = transition(level, state, Action.RIGHT)
    animation.animate_move(level, state, Action.RIGHT, result)
    start = animation.frame_meshes()
    animation.update(ROLL_MS / 2)
    assert animation.frame_meshes() != start
    assert animation.state == result.next_state
    animation.display(level, state)
    animation.update(ROLL_MS * 10)
    assert animation.state == state
    assert not animation.is_animating
    assert not animation.block_hidden


@pytest.fixture
def combined_animation(make_level):
    """A split switch closes a bridge beneath a spawned cube, causing a fall."""
    level = make_level(
        bridges=(Bridge("bridge", (Position(6, 6),), initially_open=True),),
        switches=(
            Switch(
                "split",
                Position(4, 5),
                SwitchKind.SPLIT,
                BridgeEffect(EffectMode.TOGGLE, ("bridge",)),
                (Position(6, 6), Position(6, 8)),
            ),
        ),
    )
    previous = GameState(NormalBlock(4, 3, Orientation.HORIZONTAL), bridge_mask=1)
    result = transition(level, previous, Action.RIGHT)
    assert result.outcome is Outcome.LOST
    animation = BoardAnimation(level, previous)
    animation.animate_move(level, previous, Action.RIGHT, result)
    return animation


def test_combined_animation_phase_boundaries(combined_animation):
    animation = combined_animation
    state = animation.state
    assert animation.duration_ms == ROLL_MS + TRANSFORM_MS + BRIDGE_MS + FALL_MS
    assert animation.fall_support == (Position(6, 8),)
    assert animation.phase == "roll"
    initial_meshes = animation.frame_meshes()
    animation.update(-100)
    assert animation.elapsed_ms == 0
    assert animation.frame_meshes() == initial_meshes
    animation.update(ROLL_MS - 1)
    assert animation.phase == "roll"
    animation.update(1)
    assert animation.phase == "transform"
    assert animation.bridge_openness("bridge") == 1
    assert [opacity for _, opacity in animation.frame_meshes()] == [1, 0, 0]
    animation.update(TRANSFORM_MS / 2)
    assert [opacity for _, opacity in animation.frame_meshes()] == [0.5, 0.5, 0.5]
    animation.update(TRANSFORM_MS / 2)
    assert animation.phase == "bridge"
    final_meshes = animation.frame_meshes()
    for (actual, opacity), expected in zip(final_meshes, block_meshes(state.block), strict=True):
        assert opacity == 1
        assert (actual.label, actual.active) == (expected.label, expected.active)
        for actual_point, expected_point in zip(actual.vertices, expected.vertices, strict=True):
            assert actual_point == pytest.approx(expected_point)
    animation.update(BRIDGE_MS / 2)
    assert animation.bridge_openness("bridge") == pytest.approx(0.5)
    assert animation.frame_meshes() == final_meshes
    animation.update(BRIDGE_MS / 2)
    assert animation.phase == "fall"
    assert animation.falling_outcome is Outcome.LOST
    assert animation.bridge_openness("bridge") == 0
    animation.update(FALL_MS - 1)
    assert animation.is_animating
    assert animation.frame_meshes() != final_meshes
    animation.update(1)
    assert not animation.is_animating
    assert animation.phase == ""
    assert animation.falling_outcome is None
    assert animation.block_hidden
    assert animation.fall_support == ()
    assert animation.state == state


@pytest.mark.parametrize(
    "elapsed",
    [ROLL_MS / 2, ROLL_MS + 1, ROLL_MS + TRANSFORM_MS + 1, ROLL_MS + TRANSFORM_MS + BRIDGE_MS + 1],
)
def test_cancel_clears_every_phase_before_next_move(combined_animation, elapsed):
    animation = combined_animation
    animation.update(elapsed)
    state = animation.state
    animation.cancel_animation()
    animation.update(10_000)
    assert animation.state == state
    assert not animation.is_animating
    assert not animation.block_hidden
    assert animation.fall_support == ()
    assert animation.elapsed_ms == 0
    level = builtin_levels()[0]
    previous = initial_state(level)
    result = transition(level, previous, Action.RIGHT)
    animation.animate_move(level, previous, Action.RIGHT, result)
    assert animation.duration_ms == ROLL_MS
    animation.update(ROLL_MS)
    assert not animation.is_animating
    assert not animation.block_hidden
    assert animation.state == result.next_state


def test_large_update_finishes_all_phases(combined_animation):
    animation = combined_animation
    animation.update(10_000)
    assert not animation.is_animating
    assert animation.block_hidden
    assert animation.bridge_openness("bridge") == 0
    animation.update(10_000)
    assert animation.block_hidden
    assert animation.elapsed_ms == 0
