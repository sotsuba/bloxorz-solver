"""Behavioral tests for rolling, support and advanced mechanisms."""

from dataclasses import FrozenInstanceError

import pytest

from bloxorz_solver.game.rules import (
    initial_state,
    is_goal,
    legal_actions,
    occupied_cells,
    transition,
)
from bloxorz_solver.game.state import (
    Action,
    Bridge,
    BridgeEffect,
    EffectMode,
    EventType,
    GameState,
    NormalBlock,
    Orientation,
    Outcome,
    Position,
    SplitBlock,
    Switch,
    SwitchKind,
)

S, H, V = Orientation.STANDING, Orientation.HORIZONTAL, Orientation.VERTICAL


@pytest.mark.parametrize(
    ("orientation", "action", "expected"),
    [
        (S, Action.UP, (2, 4, V)),
        (S, Action.DOWN, (5, 4, V)),
        (S, Action.LEFT, (4, 2, H)),
        (S, Action.RIGHT, (4, 5, H)),
        (H, Action.UP, (3, 4, H)),
        (H, Action.DOWN, (5, 4, H)),
        (H, Action.LEFT, (4, 3, S)),
        (H, Action.RIGHT, (4, 6, S)),
        (V, Action.UP, (3, 4, S)),
        (V, Action.DOWN, (6, 4, S)),
        (V, Action.LEFT, (4, 3, V)),
        (V, Action.RIGHT, (4, 5, V)),
    ],
)
def test_twelve_rolls(make_level, orientation, action, expected):
    level = make_level()
    state = GameState(NormalBlock(4, 4, orientation))
    result = transition(level, state, action)
    assert result.outcome is Outcome.MOVED
    assert result.next_state.block == NormalBlock(*expected)
    assert state.block == NormalBlock(4, 4, orientation)
    assert result == transition(level, state, action)


@pytest.mark.parametrize(
    ("block", "cells"),
    [
        (NormalBlock(2, 3, S), ((2, 3),)),
        (NormalBlock(2, 3, H), ((2, 3), (2, 4))),
        (NormalBlock(2, 3, V), ((2, 3), (3, 3))),
        (SplitBlock(Position(1, 1), Position(3, 3)), ((1, 1), (3, 3))),
    ],
)
def test_occupied_cells(block, cells):
    assert occupied_cells(block) == cells


def test_state_is_immutable_and_bridge_mask_changes_identity():
    state = GameState(NormalBlock(1, 1))
    assert len({state, GameState(state.block, 1)}) == 2
    with pytest.raises(FrozenInstanceError):
        state.bridge_mask = 2


def test_out_of_bounds_is_loss(make_level):
    level = make_level(start=(0, 0))
    result = transition(level, initial_state(level), Action.UP)
    assert result.outcome is Outcome.LOST
    assert result.reason == "out_of_bounds"
    assert Action.UP not in legal_actions(level, initial_state(level))


def test_void_is_loss(make_level):
    level = make_level(grid=("S.#G",), start=(0, 0), goal=(0, 3))
    result = transition(level, initial_state(level), Action.RIGHT)
    assert result.outcome is Outcome.LOST
    assert result.reason == "unsupported"


def test_fragile_supports_lying_but_not_standing(make_level):
    level = make_level(grid=("S..FG",), start=(0, 0), goal=(0, 4))
    lying = GameState(NormalBlock(0, 1, H))
    assert transition(level, initial_state(level), Action.RIGHT).outcome is Outcome.MOVED
    assert transition(level, lying, Action.RIGHT).reason == "fragile"


def test_only_complete_standing_block_wins(make_level):
    level = make_level(grid=("S..G.",), start=(0, 0), goal=(0, 3))
    assert transition(level, GameState(NormalBlock(0, 1, H)), Action.RIGHT).outcome is Outcome.WON
    assert not is_goal(level, GameState(NormalBlock(0, 2, H)))
    assert not is_goal(level, GameState(SplitBlock(Position(0, 3), Position(0, 0))))


def test_soft_switch_opens_bridge_before_final_support_check(make_level):
    bridge = Bridge("b", (Position(0, 2),))
    switch = Switch("s", Position(0, 1), SwitchKind.SOFT, BridgeEffect(EffectMode.TOGGLE, ("b",)))
    level = make_level(
        grid=("S.#G",), start=(0, 0), goal=(0, 3), bridges=(bridge,), switches=(switch,)
    )
    result = transition(level, initial_state(level), Action.RIGHT)
    assert result.outcome is Outcome.MOVED
    assert result.next_state.bridge_mask == 1


def test_closed_bridge_is_void_and_initial_mask_is_stable(make_level):
    bridges = (Bridge("z", (Position(0, 2),), True), Bridge("a", (Position(0, 1),)))
    level = make_level(grid=("S##G",), start=(0, 0), goal=(0, 3), bridges=bridges)
    assert initial_state(level).bridge_mask == 2
    assert transition(level, initial_state(level), Action.RIGHT).outcome is Outcome.LOST


@pytest.mark.parametrize("kind", [SwitchKind.SOFT, SwitchKind.HEAVY])
def test_switch_activates_when_its_press_condition_becomes_true(make_level, kind):
    bridge = Bridge("b", (Position(8, 0),))
    switch = Switch("s", Position(4, 5), kind, BridgeEffect(EffectMode.TOGGLE, ("b",)))
    level = make_level(bridges=(bridge,), switches=(switch,))
    state = GameState(NormalBlock(4, 4))
    result = transition(level, state, Action.RIGHT)
    assert result.next_state.bridge_mask == (1 if kind is SwitchKind.SOFT else 0)
    standing = transition(level, GameState(NormalBlock(4, 6, H)), Action.LEFT)
    assert standing.next_state.bridge_mask == 1


def test_heavy_switch_fires_when_lying_block_becomes_standing_on_it(make_level):
    bridge = Bridge("b", (Position(8, 0),))
    switch = Switch("s", Position(4, 4), SwitchKind.HEAVY, BridgeEffect(EffectMode.TOGGLE, ("b",)))
    level = make_level(bridges=(bridge,), switches=(switch,))
    result = transition(level, GameState(NormalBlock(4, 2, H)), Action.RIGHT)
    assert result.next_state.bridge_mask == 1


def test_switch_does_not_toggle_again_while_other_cube_moves_or_on_swap(make_level):
    bridge = Bridge("b", (Position(8, 0),))
    switch = Switch("s", Position(4, 4), SwitchKind.SOFT, BridgeEffect(EffectMode.TOGGLE, ("b",)))
    level = make_level(bridges=(bridge,), switches=(switch,))
    state = GameState(SplitBlock(Position(4, 4), Position(6, 6), 1), 1)
    moved = transition(level, state, Action.RIGHT)
    swapped = transition(level, moved.next_state, Action.SWAP_ACTIVE_CUBE)
    assert moved.next_state.bridge_mask == swapped.next_state.bridge_mask == 1
    assert not swapped.events


@pytest.mark.parametrize("is_open", [True, False])
def test_set_bridge_effect_is_idempotent(make_level, is_open):
    bridge = Bridge("b", (Position(8, 0),), not is_open)
    effect = BridgeEffect(EffectMode.SET, ("b",), is_open)
    switch = Switch("s", Position(4, 5), SwitchKind.SOFT, effect)
    level = make_level(bridges=(bridge,), switches=(switch,))
    first = transition(level, initial_state(level), Action.RIGHT)
    departed = transition(level, first.next_state, Action.LEFT)
    second = transition(level, departed.next_state, Action.RIGHT)
    assert first.next_state.bridge_mask == second.next_state.bridge_mask == int(is_open)


def test_simultaneous_switches_execute_by_id(make_level):
    bridge = Bridge("b", (Position(8, 0),))
    switches = (
        Switch("z", Position(4, 6), SwitchKind.SOFT, BridgeEffect(EffectMode.SET, ("b",), False)),
        Switch("a", Position(4, 5), SwitchKind.SOFT, BridgeEffect(EffectMode.SET, ("b",), True)),
    )
    level = make_level(bridges=(bridge,), switches=switches)
    result = transition(level, initial_state(level), Action.RIGHT)
    assert result.next_state.bridge_mask == 0
    assert [
        event.subject for event in result.events if event.kind is EventType.SWITCH_TRIGGERED
    ] == ["a", "z"]


def test_closing_bridge_beneath_stationary_cube_causes_loss(make_level):
    bridge = Bridge("b", (Position(0, 1),), True)
    switch = Switch("s", Position(0, 4), SwitchKind.SOFT, BridgeEffect(EffectMode.TOGGLE, ("b",)))
    level = make_level(
        grid=("S#...G",), start=(0, 0), goal=(0, 5), bridges=(bridge,), switches=(switch,)
    )
    state = GameState(SplitBlock(Position(0, 3), Position(0, 1)), 1)
    assert transition(level, state, Action.RIGHT).outcome is Outcome.LOST


def test_split_teleports_and_swap_preserves_cube_identity(make_level):
    spawns = (Position(1, 1), Position(7, 7))
    switch = Switch("split", Position(4, 6), SwitchKind.SPLIT, spawn_positions=spawns)
    level = make_level(switches=(switch,))
    result = transition(level, GameState(NormalBlock(4, 4, H)), Action.RIGHT)
    assert result.next_state.block == SplitBlock(*spawns)
    assert EventType.BLOCK_SPLIT in {event.kind for event in result.events}
    swapped = transition(level, result.next_state, Action.SWAP_ACTIVE_CUBE)
    assert swapped.next_state.block == SplitBlock(*spawns, active_cube=1)


def test_teleport_does_not_activate_spawn_switch(make_level):
    bridge = Bridge("b", (Position(8, 0),))
    switches = (
        Switch(
            "split",
            Position(4, 6),
            SwitchKind.SPLIT,
            spawn_positions=(Position(1, 1), Position(7, 7)),
        ),
        Switch("soft", Position(1, 1), SwitchKind.SOFT, BridgeEffect(EffectMode.TOGGLE, ("b",))),
    )
    level = make_level(bridges=(bridge,), switches=switches)
    result = transition(level, GameState(NormalBlock(4, 4, H)), Action.RIGHT)
    assert result.next_state.bridge_mask == 0


@pytest.mark.parametrize(
    ("first", "second", "action", "expected"),
    [
        ((4, 2), (4, 4), Action.RIGHT, NormalBlock(4, 3, H)),
        ((2, 4), (4, 4), Action.DOWN, NormalBlock(3, 4, V)),
    ],
)
def test_cubes_merge_on_adjacency(make_level, first, second, action, expected):
    state = GameState(SplitBlock(Position(*first), Position(*second)))
    result = transition(make_level(), state, action)
    assert result.next_state.block == expected
    assert EventType.BLOCK_MERGED in {event.kind for event in result.events}


def test_cube_overlap_is_invalid(make_level):
    state = GameState(SplitBlock(Position(4, 4), Position(4, 5)))
    result = transition(make_level(), state, Action.RIGHT)
    assert result.outcome is Outcome.INVALID
    assert result.next_state == state


def test_solo_cube_survives_fragile(make_level):
    level = make_level(grid=("SF..G",), start=(0, 0), goal=(0, 4))
    state = GameState(SplitBlock(Position(0, 0), Position(0, 4)))
    result = transition(level, state, Action.RIGHT)
    assert result.outcome is Outcome.MOVED
    assert result.next_state.block.cube_a == (0, 1)


@pytest.mark.parametrize("kind", [SwitchKind.SOFT, SwitchKind.HEAVY, SwitchKind.SPLIT])
def test_solo_cube_activates_soft_but_not_heavy_or_split(make_level, kind):
    bridge = Bridge("b", (Position(8, 0),))
    switch = Switch(
        "s",
        Position(4, 5),
        kind,
        BridgeEffect(EffectMode.TOGGLE, ("b",)),
        (Position(1, 1), Position(7, 7)) if kind is SwitchKind.SPLIT else (),
    )
    level = make_level(bridges=(bridge,), switches=(switch,))
    state = GameState(SplitBlock(Position(4, 4), Position(7, 7)))
    result = transition(level, state, Action.RIGHT)
    assert result.next_state.bridge_mask == int(kind is SwitchKind.SOFT)
    assert result.next_state.block.cube_a == (4, 5)


def test_soft_switch_retriggers_only_after_departing(make_level):
    bridge = Bridge("b", (Position(8, 0),))
    switch = Switch("s", Position(4, 5), SwitchKind.SOFT, BridgeEffect(EffectMode.TOGGLE, ("b",)))
    level = make_level(bridges=(bridge,), switches=(switch,))
    state = GameState(SplitBlock(Position(4, 4), Position(7, 7)))
    first = transition(level, state, Action.RIGHT)
    departed = transition(level, first.next_state, Action.LEFT)
    second = transition(level, departed.next_state, Action.RIGHT)
    assert first.next_state.bridge_mask == 1
    assert departed.next_state.bridge_mask == 1
    assert second.next_state.bridge_mask == 0


@pytest.mark.parametrize("opens_spawn", [True, False])
def test_split_checks_dynamic_spawn_support_after_bridge_effect(make_level, opens_spawn):
    bridge = Bridge("b", (Position(1, 1),))
    effect = BridgeEffect(EffectMode.SET, ("b",), True) if opens_spawn else None
    switch = Switch("s", Position(4, 6), SwitchKind.SPLIT, effect, (Position(1, 1), Position(7, 7)))
    level = make_level(bridges=(bridge,), switches=(switch,))
    result = transition(level, GameState(NormalBlock(4, 4, H)), Action.RIGHT)
    assert result.outcome is (Outcome.MOVED if opens_spawn else Outcome.LOST)


def test_adjacent_teleport_spawns_remain_split_on_swap(make_level):
    switch = Switch(
        "s", Position(4, 6), SwitchKind.SPLIT, spawn_positions=(Position(1, 1), Position(1, 2))
    )
    level = make_level(switches=(switch,))
    split = transition(level, GameState(NormalBlock(4, 4, H)), Action.RIGHT)
    assert isinstance(split.next_state.block, SplitBlock)
    swapped = transition(level, split.next_state, Action.SWAP_ACTIVE_CUBE)
    assert isinstance(swapped.next_state.block, SplitBlock)
    assert not swapped.events


def test_swap_of_complete_block_is_invalid(make_level):
    level = make_level()
    state = initial_state(level)
    result = transition(level, state, Action.SWAP_ACTIVE_CUBE)
    assert result.outcome is Outcome.INVALID
    assert result.next_state == state


@pytest.mark.parametrize("action", ["unknown", "swap", None])
def test_invalid_action_does_not_crash_or_change_state(make_level, action):
    level = make_level()
    state = initial_state(level)
    result = transition(level, state, action)
    assert result.outcome is Outcome.INVALID
    assert result.next_state == state
    assert result.reason == "invalid_action"


def test_lost_state_has_no_legal_actions(make_level):
    # A roll from this unsupported state could reach floor again. Search must
    # treat the loss as terminal rather than rescuing the fallen block.
    level = make_level()
    state = GameState(NormalBlock(-1, 4, Orientation.VERTICAL))
    assert legal_actions(level, state) == ()
