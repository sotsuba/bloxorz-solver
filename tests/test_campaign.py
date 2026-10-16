"""Playable campaign progression and required mechanics along fixed winning routes."""

import pytest

from bloxorz_solver.game.rules import initial_state, occupied_cells, transition
from bloxorz_solver.game.state import Action, EventType, Outcome, SplitBlock
from bloxorz_solver.levels.loader import builtin_levels

ACTIONS = dict(U=Action.UP, D=Action.DOWN, L=Action.LEFT, R=Action.RIGHT, X=Action.SWAP_ACTIVE_CUBE)


@pytest.fixture(params=builtin_levels(), ids=lambda level: level.id)
def campaign_level(request):
    """Exercise every packaged stage independently."""
    return request.param


def test_ten_stages_grow_in_size_and_solution_length(stage_routes):
    levels = builtin_levels()
    assert len(levels) == 10
    assert [level.id[:2] for level in levels] == [f"{i:02}" for i in range(1, 11)]
    assert set(stage_routes) == {level.id for level in levels}
    previous = (0, 0, 0, 0)
    for level in levels:
        usable = sum(cell != "#" for row in level.grid for cell in row)
        usable += sum(len(bridge.cells) for bridge in level.bridges)
        current = (level.width, level.height, usable, len(stage_routes[level.id]))
        assert all(after > before for before, after in zip(previous, current, strict=True))
        previous = current


def test_every_stage_wins_and_uses_its_mechanisms(campaign_level, stage_routes):
    level = campaign_level
    route = stage_routes[level.id]
    state = initial_state(level)
    events = []
    visited = set(occupied_cells(state.block))
    cube_switches = set()
    for index, letter in enumerate(route):
        result = transition(level, state, ACTIONS[letter])
        expected = Outcome.WON if index == len(route) - 1 else Outcome.MOVED
        assert result.outcome is expected, (level.id, index, letter, result)
        if isinstance(state.block, SplitBlock):
            cube_switches.update(
                event.subject for event in result.events if event.kind is EventType.SWITCH_TRIGGERED
            )
        state = result.next_state
        events.extend((event.kind, event.subject) for event in result.events)
        visited.update(occupied_cells(state.block))

    triggered = {subject for kind, subject in events if kind is EventType.SWITCH_TRIGGERED}
    assert triggered == {switch.id for switch in level.switches}
    for bridge in level.bridges:
        assert visited.intersection(bridge.cells), (level.id, bridge.id)
    fragile = {
        (r, c) for r, row in enumerate(level.grid) for c, cell in enumerate(row) if cell == "F"
    }
    if fragile:
        assert visited.intersection(fragile), level.id

    splits = [subject for kind, subject in events if kind is EventType.BLOCK_SPLIT]
    merges = [subject for kind, subject in events if kind is EventType.BLOCK_MERGED]
    assert len(splits) == len(merges)
    if level.id.startswith(("09_", "10_")):
        assert len(splits) == 2
        first_merge = events.index((EventType.BLOCK_MERGED, ""))
        heavy = events.index((EventType.SWITCH_TRIGGERED, "upper_button"))
        second_split = events.index((EventType.BLOCK_SPLIT, "second_split"))
        assert first_merge < heavy < second_split
    if level.id == "06_bridge_builders":
        assert "soft" in cube_switches
    if level.id.startswith(("08_", "10_")):
        prepared = events.index((EventType.BRIDGE_OPENED, "exit"))
        locked = events.index((EventType.BRIDGE_CLOSED, "entry"))
        assert prepared < locked
