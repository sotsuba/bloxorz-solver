"""Terminal results wait for a modal action after the animation finishes."""

from concurrent.futures import Future

import pygame
import pygame_gui
import pytest

from bloxorz_solver.game.rules import initial_state, transition
from bloxorz_solver.game.session import SessionStatus
from bloxorz_solver.game.state import Action, Outcome, SplitBlock
from bloxorz_solver.solvers.base import SearchResult
from bloxorz_solver.ui.animation import FALL_MS, ROLL_MS
from bloxorz_solver.ui.app import GameApp
from bloxorz_solver.ui.view import NOTICE_FADE_MS, NOTICE_MS


@pytest.fixture
def game():
    app = GameApp()
    app.set_mode("Manual")
    yield app
    app.close()
    pygame.quit()


def drop(app):
    app.play(Action.UP)
    app.update(ROLL_MS + FALL_MS)


def press_result(game, name):
    widget = game.view.result_buttons[name]
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        game.handle_event(pygame.event.Event(kind, button=1, pos=widget.rect.center))
    for _ in range(8):
        for event in pygame.event.get():
            game.handle_event(event)
        game.view.update(16)


def test_drop_finishes_animation_before_popup_and_retry(game):
    start = initial_state(game.session.level)
    game.play(Action.UP)
    assert game.session.status is SessionStatus.LOST
    game.update(ROLL_MS + FALL_MS - 1)
    assert game.animation.is_animating
    assert not game.view.result_open
    game.update(1)
    assert game.session.status is SessionStatus.LOST
    assert game.view.result_title == "You lose!"
    assert game.animation.block_hidden
    window = game.view.result_window
    game.update(5000)
    assert game.view.result_window is window
    game.play(Action.RIGHT)
    assert game.session.action_count == 1
    press_result(game, "restart")
    assert not game.view.result_open
    assert game.session.status is SessionStatus.PLAYING
    assert game.session.state == start
    assert game.session.action_count == 0
    assert not game.animation.block_hidden


def test_notice_holds_then_fades_with_elapsed_time_and_disappears(game):
    game.view.show_notice("Search failed")
    game.set_playback_speed(4.0)
    game.update(NOTICE_MS - NOTICE_FADE_MS)
    assert game.view.notice_alpha == 255
    game.update(NOTICE_FADE_MS / 2)
    assert game.view.notice_alpha == 128
    before = game.view.notice_remaining_ms
    game.update(-100)
    assert game.view.notice_remaining_ms == before
    game.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=800, h=600))
    game.draw()
    assert game.view.notice_alpha == 128
    game.update(NOTICE_FADE_MS / 2)
    assert game.view.notice_alpha == 0
    assert not game.view.notice_text
    assert game.view._notice_surface is None
    game.draw()


def test_restart_and_stage_changes_clear_popup(game):
    drop(game)
    game.restart()
    assert not game.view.result_open
    drop(game)
    game.load_stage(1)
    assert not game.view.result_open
    assert game.session.state == initial_state(game.levels[1])


@pytest.mark.parametrize("level_index", [2, 5])
def test_drop_restores_bridges_and_split_cubes(game, stage_routes, level_index):
    game.load_stage(level_index)
    actions = dict(U=Action.UP, D=Action.DOWN, L=Action.LEFT, R=Action.RIGHT,
                   X=Action.SWAP_ACTIVE_CUBE)
    for letter in stage_routes[game.session.level.id]:
        game.play(actions[letter])
        game.update(2000)
        changed = (game.session.state.bridge_mask != initial_state(game.session.level).bridge_mask
                   if level_index == 2 else isinstance(game.session.state.block, SplitBlock))
        if changed:
            break
    assert changed
    lost_action = next(action for action in Action
                       if transition(game.session.level, game.session.state, action).outcome
                       is Outcome.LOST)
    game.play(lost_action)
    game.update(2000)
    assert game.view.result_open
    press_result(game, "restart")
    assert game.session.state == initial_state(game.session.level)
    assert game.session.status is SessionStatus.PLAYING


def test_loss_in_playback_discards_the_remaining_route(game, monkeypatch):
    future = Future()
    future.set_result(SearchResult(["up", "right"], 0, 0, 0, 2))
    monkeypatch.setattr(game._executor, "submit", lambda *args: future)
    game.set_mode("BFS")
    game.solve()
    game.update(0)
    assert game.session.status is SessionStatus.LOST
    assert game._solution
    game.update(2000)
    assert not game._solution and game.last_result is None
    assert game.solution_total == game.solution_completed == 0
    assert not game.can_solve
    assert game.view.result_open
    press_result(game, "restart")
    assert game.can_solve
    game.update(2000)
    assert game.session.action_count == 0


def test_removed_title_status_instructions_and_json_controls_stay_removed(game):
    assert set(game.view.labels) == {"stage", "mode", "heuristic", "speed"}
    assert set(game.view.widgets) == {"solve", "restart", "next", "playback", "step"}
    assert not hasattr(game.view, "status")
    assert not hasattr(game.view, "open_button")
    start, level_count = game.session.state, len(game.levels)
    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    game.handle_event(pygame.event.Event(pygame.DROPFILE, file="/unused/level.json"))
    assert game.session.state == start
    assert len(game.levels) == level_count
    assert game.can_play


def test_resize_and_mode_changes_keep_controls_at_the_top(game):
    game.set_mode("A*")
    game.update(0)
    game.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=800, h=600))
    game.set_mode("Manual")
    drop(game)
    game.update(0)
    sidebar = game.view.sidebar
    assert sidebar.scrollable_container.rect.top == sidebar.rect.top
    assert game.view.labels["stage"].rect.top == sidebar.rect.top + 8


@pytest.mark.parametrize("size", [(800, 600), (1160, 800), (2320, 1600)])
def test_modal_blocks_underlying_input_and_survives_resize(game, size):
    drop(game)
    for key in (pygame.K_ESCAPE, pygame.K_RIGHT, pygame.K_PAGEDOWN):
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
    game.handle_event(pygame.event.Event(
        pygame_gui.UI_BUTTON_PRESSED, ui_element=game.view.widgets["restart"]))
    assert game.session.status is SessionStatus.LOST
    assert game.active_index == 0
    game.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=size[0], h=size[1]))
    game.draw()
    window = game.view.result_window
    assert window.rect.center == game.screen.get_rect().center
    assert game.screen.get_rect().contains(window.rect)
    assert all(window.rect.contains(button.rect) for button in game.view.result_buttons.values())
    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
    assert not game.view.result_open
    assert game.can_play


@pytest.mark.parametrize("final", [False, True])
def test_win_popup_actions_and_final_stage(game, stage_routes, final):
    game.load_stage(len(game.levels) - 1 if final else 0)
    actions = dict(U=Action.UP, D=Action.DOWN, L=Action.LEFT, R=Action.RIGHT,
                   X=Action.SWAP_ACTIVE_CUBE)
    for letter in stage_routes[game.session.level.id]:
        game.play(actions[letter])
        if game.session.status is SessionStatus.WON:
            assert not game.view.result_open
            game.update(ROLL_MS + FALL_MS - 1)
            assert not game.view.result_open
        else:
            game.update(2000)
    game.update(2000)
    assert game.view.result_title == ("All stages complete!" if final else "You win!")
    assert set(game.view.result_buttons) == ({"restart"} if final else {"restart", "next"})
    press_result(game, "restart" if final else "next")
    assert not game.view.result_open
    assert game.can_play
    assert game.active_index == (len(game.levels) - 1 if final else 1)
