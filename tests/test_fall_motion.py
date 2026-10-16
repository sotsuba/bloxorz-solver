"""Regression checks for a block tipping off its last supporting floor cell."""

from math import dist

import pytest

from bloxorz_solver.game.rules import supported_cells, transition
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
    SplitBlock,
    Switch,
    SwitchKind,
)
from bloxorz_solver.ui.motion import (
    BLOCK_INSET,
    FACES,
    block_meshes,
    clip_height,
    drop_meshes,
    fall_meshes,
)


def assert_clear_of_support(mesh, support, direction):
    """Every portion below floor height must lie beyond the supporting tile's edge."""
    axis = 0 if direction in (Action.LEFT, Action.RIGHT) else 1
    positive = direction in (Action.RIGHT, Action.DOWN)
    edge = (support.col if axis == 0 else support.row) + int(positive)
    sign = 1 if positive else -1
    vertices = tuple((c, r, z - BLOCK_INSET) for c, r, z in mesh.vertices)
    for indices in FACES:
        below = clip_height(tuple(vertices[index] for index in indices), above=False)
        if any(point[2] < -1e-8 for point in below):
            assert all(sign * (point[axis] - edge) >= -1e-8 for point in below)


@pytest.mark.parametrize(
    ("start", "action"),
    [
        ((4, 1), Action.LEFT),
        ((4, 8), Action.RIGHT),
        ((1, 4), Action.UP),
        ((8, 4), Action.DOWN),
    ],
)
def test_one_cell_outside_tips_without_passing_through_floor(make_level, start, action):
    level = make_level(start=start)
    result = transition(level, GameState(NormalBlock(*start)), action)
    assert result.outcome is Outcome.LOST
    support = supported_cells(level, result.next_state)
    assert len(support) == 1
    source = block_meshes(result.next_state.block)[0]
    for frame in range(61):
        progress = frame / 60
        mesh = fall_meshes(result.next_state.block, support, progress, tumble=action)[0]
        assert_clear_of_support(mesh, support[0], action)
        assert dist(mesh.vertices[0], mesh.vertices[6]) == pytest.approx(
            dist(source.vertices[0], source.vertices[6])
        )
    assert fall_meshes(result.next_state.block, support, 0, tumble=action) == (source,)


@pytest.mark.parametrize(
    ("block", "action", "void", "fall_direction"),
    [
        (NormalBlock(4, 4, Orientation.HORIZONTAL), Action.UP, (3, 4), Action.LEFT),
        (NormalBlock(4, 4, Orientation.HORIZONTAL), Action.UP, (3, 5), Action.RIGHT),
        (NormalBlock(4, 4, Orientation.VERTICAL), Action.RIGHT, (4, 5), Action.UP),
        (NormalBlock(4, 4, Orientation.VERTICAL), Action.RIGHT, (5, 5), Action.DOWN),
    ],
)
def test_tipping_uses_missing_cell_instead_of_last_key(
    make_level, block, action, void, fall_direction
):
    rows = [list("..........") for _ in range(10)]
    rows[4][4], rows[8][8] = "S", "G"
    rows[void[0]][void[1]] = "#"
    level = make_level(grid=["".join(row) for row in rows])
    result = transition(level, GameState(block), action)
    assert result.outcome is Outcome.LOST
    support = supported_cells(level, result.next_state)
    for frame in range(61):
        mesh = fall_meshes(result.next_state.block, support, frame / 60, tumble=action)[0]
        assert_clear_of_support(mesh, support[0], fall_direction)


def test_support_uses_bridge_configuration_after_switch_activation(make_level):
    bridge = Bridge("b", (Position(3, 4),), True)
    switch = Switch("s", Position(3, 5), SwitchKind.SOFT, BridgeEffect(EffectMode.TOGGLE, ("b",)))
    level = make_level(bridges=(bridge,), switches=(switch,))
    result = transition(level, GameState(NormalBlock(4, 4, Orientation.HORIZONTAL), 1), Action.UP)
    assert result.outcome is Outcome.LOST
    assert result.next_state.bridge_mask == 0
    support = supported_cells(level, result.next_state)
    assert support == (Position(3, 5),)
    for progress in (0.1, 0.3, 0.5, 0.7, 0.9):
        mesh = fall_meshes(result.next_state.block, support, progress, tumble=Action.UP)[0]
        assert_clear_of_support(mesh, support[0], Action.LEFT)


def test_tip_and_free_fall_have_a_continuous_join():
    block = NormalBlock(2, 2, Orientation.HORIZONTAL)
    support = (Position(2, 2),)
    before = fall_meshes(block, support, 0.5 - 1e-7, tumble=Action.RIGHT)[0]
    after = fall_meshes(block, support, 0.5 + 1e-7, tumble=Action.RIGHT)[0]
    assert all(dist(a, b) < 1e-5 for a, b in zip(before.vertices, after.vertices, strict=True))


def test_fully_unsupported_block_keeps_existing_free_fall():
    block = NormalBlock(-2, 3, Orientation.VERTICAL)
    for progress in (0, 0.25, 0.5, 0.75, 1):
        assert fall_meshes(block, (), progress, tumble=Action.UP) == drop_meshes(
            block_meshes(block), progress, tumble=Action.UP
        )


def test_supported_split_cube_stays_on_the_floor():
    block = SplitBlock(Position(2, 2), Position(-1, 5), 1)
    source = block_meshes(block)
    for progress in (0.2, 0.5, 0.8):
        meshes = fall_meshes(block, (block.cube_a,), progress, tumble=Action.UP)
        assert meshes[0] == source[0]
        assert meshes[1] != source[1]
