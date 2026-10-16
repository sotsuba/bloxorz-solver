"""Session outcomes, counters and complete restart behavior."""

from bloxorz.application.game_session import GameSession, SessionStatus
from bloxorz.domain.engine import initial_state
from bloxorz.domain.models import Action, SplitBlock
from bloxorz.infrastructure.level_loader import builtin_levels


def test_new_session_starts_at_initial_state(make_level):
    level = make_level()
    session = GameSession(level)
    assert session.state == initial_state(level)
    assert session.status is SessionStatus.PLAYING
    assert session.roll_count == session.swap_count == session.action_count == 0


def test_winning_session_stops_accepting_input(make_level):
    session = GameSession(make_level(grid=("S..G",), start=(0, 0), goal=(0, 3)))
    session.apply_action(Action.RIGHT)
    session.apply_action(Action.RIGHT)
    assert session.status is SessionStatus.WON
    assert session.roll_count == 2
    assert session.apply_action(Action.LEFT) is None
    assert session.roll_count == 2


def test_fall_is_loss_and_restart_restores_game(make_level):
    session = GameSession(make_level(start=(0, 0)))
    session.apply_action(Action.UP)
    assert session.status is SessionStatus.LOST
    assert session.roll_count == 1
    assert session.apply_action(Action.DOWN) is None
    session.restart()
    assert session.state == initial_state(session.level)
    assert session.status is SessionStatus.PLAYING
    assert session.action_count == 0
    assert session.last_result is None


def test_invalid_swap_does_not_count(make_level):
    session = GameSession(make_level())
    session.apply_action(Action.SWAP_ACTIVE_CUBE)
    assert session.action_count == 0


def test_split_swaps_and_restart_reset_all_dynamic_data():
    level = next(level for level in builtin_levels() if level.id == "06_bridge_builders")
    session = GameSession(level)
    for _ in range(6):
        session.apply_action(Action.RIGHT)
    session.apply_action(Action.SWAP_ACTIVE_CUBE)
    assert isinstance(session.state.block, SplitBlock)
    assert session.state.bridge_mask == 1
    assert (session.roll_count, session.swap_count, session.action_count) == (6, 1, 7)
    session.restart()
    assert session.state == initial_state(level)
    assert session.state.bridge_mask == 0
    assert session.action_count == 0
