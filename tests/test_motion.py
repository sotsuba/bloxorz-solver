"""Rigid animation geometry must agree with engine endpoints without changing state."""

from math import dist

import pytest

from bloxorz.domain.engine import transition
from bloxorz.domain.models import Action, GameState, NormalBlock, Orientation, Position, SplitBlock
from bloxorz.presentation.motion import (
    BLOCK_INSET,
    block_meshes,
    bridge_vertices,
    clip_height,
    drop_meshes,
    roll_meshes,
)


def coordinates(mesh):
    return sorted(tuple(round(value, 6) for value in point) for point in mesh.vertices)


@pytest.mark.parametrize("orientation", list(Orientation))
@pytest.mark.parametrize("action", [Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT])
def test_rigid_quarter_turn_matches_engine_endpoint(make_level, orientation, action):
    state = GameState(NormalBlock(4, 4, orientation))
    destination = transition(make_level(), state, action).next_state
    start = block_meshes(state.block)[0]
    middle = roll_meshes(state.block, action, 0.5)[0]
    end = roll_meshes(state.block, action, 1)[0]
    assert coordinates(roll_meshes(state.block, action, 0)[0]) == coordinates(start)
    assert coordinates(end) == coordinates(block_meshes(destination.block)[0])
    assert dist(start.vertices[0], start.vertices[6]) == pytest.approx(
        dist(middle.vertices[0], middle.vertices[6])
    )
    assert min(point[2] for point in middle.vertices) >= BLOCK_INSET


@pytest.mark.parametrize("active_cube", [0, 1])
def test_only_active_cube_moves(active_cube):
    block = SplitBlock(Position(1, 1), Position(5, 5), active_cube)
    start = block_meshes(block)
    moved = roll_meshes(block, Action.RIGHT, 0.5)
    assert moved[1 - active_cube] == start[1 - active_cube]
    assert moved[active_cube] != start[active_cube]
    assert moved[active_cube].label == start[active_cube].label


def test_fall_accelerates_and_does_not_mutate_source():
    source = block_meshes(NormalBlock(1, 1))
    early = drop_meshes(source, 0.25)[0].vertices[0][2]
    late = drop_meshes(source, 0.5)[0].vertices[0][2]
    assert source[0].vertices[0][2] == BLOCK_INSET
    assert BLOCK_INSET - late == pytest.approx(4 * (BLOCK_INSET - early))


def test_bridge_hinge_preserves_plate_dimensions():
    closed = bridge_vertices(2, 3, 0, 0.16)
    middle = bridge_vertices(2, 3, 0.5, 0.16)
    opened = bridge_vertices(2, 3, 1, 0.16)
    assert max(point[2] for point in opened) == 0
    assert max(point[2] for point in closed) < 0
    assert dist(middle[0], middle[6]) == pytest.approx(dist(opened[0], opened[6]))


def test_goal_clips_only_the_portion_above_the_floor():
    face = ((0, 0, -1), (1, 0, -1), (1, 0, 1), (0, 0, 1))
    clipped = clip_height(face)
    assert len(clipped) == 4
    assert all(point[2] >= 0 for point in clipped)
    assert (1.0, 0.0, 0.0) in clipped
    assert clip_height(((0, 0, -2), (1, 0, -2), (1, 0, -1))) == ()
