"""Headless integration tests using actual Pygame surfaces and input events."""

import pygame
import pytest

from bloxorz_solver.game.rules import initial_state
from bloxorz_solver.game.session import SessionStatus
from bloxorz_solver.game.state import NormalBlock, Position, SplitBlock
from bloxorz_solver.ui.animation import BRIDGE_MS, FALL_MS, ROLL_MS
from bloxorz_solver.ui.app import GameApp
from bloxorz_solver.ui.motion import BLOCK_INSET, block_meshes


@pytest.fixture
def app():
    game = GameApp()
    yield game
    game.close()
    pygame.quit()


def key(app, code, *, finish=True):
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=code))
    if finish:
        app.update(2000)


def click(app, name):
    app.draw()
    viewport = app.view.viewport(app.screen)
    center = app.buttons[name].rect.center
    pos = (
        viewport.x + center[0] * viewport.width / 1160,
        viewport.y + center[1] * viewport.height / 800,
    )
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))


def test_all_stages_render_and_complete_through_keyboard(app, stage_routes):
    keys = dict(U=pygame.K_UP, D=pygame.K_DOWN, L=pygame.K_LEFT, R=pygame.K_RIGHT, X=pygame.K_SPACE)
    for index, level in enumerate(app.levels):
        app.selected_index = index
        click(app, "new_game")
        assert app.session.state == initial_state(level)
        app.draw()
        assert len(set(pygame.image.tobytes(app.view.board_surface, "RGB"))) > 20
        for letter in stage_routes[level.id]:
            key(app, keys[letter], finish=False)
            app.update(ROLL_MS // 2)
            app.draw()
            app.update(2000)
        assert app.session.status is SessionStatus.WON
        assert app.animation.block_hidden
        assert app.can_advance == (index < len(app.levels) - 1)
        app.draw()
    assert app.session.swap_count == 2
    assert app.status_text()[0] == "Stage complete"
    click(app, "restart")
    assert app.can_play
    assert app.session.action_count == 0


def test_motion_blocks_overlapping_keyboard_and_mouse_inputs(app):
    key(app, pygame.K_RIGHT, finish=False)
    state = app.session.state
    key(app, pygame.K_RIGHT, finish=False)
    key(app, pygame.K_SPACE, finish=False)
    click(app, "right")
    assert app.session.state == state
    assert app.session.roll_count == 1
    assert app.status_text()[0] == "In motion"
    app.update(ROLL_MS)
    assert app.can_play
    click(app, "right")
    assert app.session.roll_count == 2


def test_roll_has_intermediate_frames_without_changing_game_state(app):
    key(app, pygame.K_RIGHT, finish=False)
    state = app.session.state
    app.draw()
    before = pygame.image.tobytes(app.view.board_surface, "RGB")
    app.update(ROLL_MS / 2)
    app.draw()
    assert before != pygame.image.tobytes(app.view.board_surface, "RGB")
    assert app.session.state == state
    assert app.animation.phase == "roll"


@pytest.mark.parametrize("falling", [False, True])
def test_restart_cancels_all_motion(app, falling):
    key(app, pygame.K_UP if falling else pygame.K_RIGHT, finish=False)
    app.update(ROLL_MS + FALL_MS / 4 if falling else ROLL_MS / 2)
    key(app, pygame.K_r)
    assert app.session.state == initial_state(app.session.level)
    assert app.session.action_count == 0
    assert not app.animation.is_animating
    assert not app.animation.block_hidden
    assert app.animation.fall_support == ()
    app.update(5000)
    assert app.session.status is SessionStatus.PLAYING


def test_stage_selection_is_pending_until_new_game_and_cancels_motion(app):
    key(app, pygame.K_RIGHT, finish=False)
    key(app, pygame.K_PAGEDOWN, finish=False)
    assert app.session.level == app.levels[0]
    assert app.animation.is_animating
    key(app, pygame.K_RETURN, finish=False)
    assert app.session.level == app.levels[1]
    assert not app.animation.is_animating
    assert app.session.action_count == 0


def test_next_stage_only_after_win_and_goal_animation(app):
    key(app, pygame.K_n)
    assert app.session.level == app.levels[0]
    for _ in range(3):
        key(app, pygame.K_RIGHT)
    key(app, pygame.K_RIGHT, finish=False)
    assert app.session.status is SessionStatus.WON
    assert not app.can_advance
    app.update(ROLL_MS + FALL_MS / 2)
    assert app.animation.phase == "fall"
    vertices = app.animation.frame_meshes()[0][0].vertices
    assert min(p[2] for p in vertices) < 0 < max(p[2] for p in vertices)
    app.draw()
    app.update(2000)
    assert app.animation.block_hidden
    key(app, pygame.K_RIGHT)
    assert app.animation.block_hidden
    click(app, "next")
    assert app.session.level == app.levels[1]
    assert app.can_play


def test_bridge_motion_opens_and_closes_after_landing(app):
    app.selected_index = 2
    app.start_selected_level()
    key(app, pygame.K_UP)
    key(app, pygame.K_RIGHT)
    for before, after in ((0, 1), (1, 0)):
        key(app, pygame.K_RIGHT, finish=False)
        assert app.animation.bridge_openness("crossing") == before
        app.update(ROLL_MS + BRIDGE_MS / 2)
        assert app.animation.phase == "bridge"
        assert app.animation.bridge_openness("crossing") == pytest.approx(0.5)
        app.draw()
        app.update(2000)
        assert app.animation.bridge_openness("crossing") == after
        if after:
            key(app, pygame.K_LEFT)
    app.restart()
    assert app.session.state.bridge_mask == 0


def test_split_swap_and_merge(app, stage_routes):
    app.selected_index = 5
    app.start_selected_level()
    before, after = stage_routes["06_bridge_builders"].split("X")
    keys = dict(U=pygame.K_UP, D=pygame.K_DOWN, L=pygame.K_LEFT, R=pygame.K_RIGHT)
    for letter in before:
        key(app, keys[letter])
    assert isinstance(app.session.state.block, SplitBlock)
    click(app, "swap")
    assert app.session.state.block.active_cube == 1
    assert app.session.swap_count == 1
    for letter in after:
        key(app, keys[letter])
    assert isinstance(app.session.state.block, NormalBlock)
    assert app.session.status is SessionStatus.WON


def test_overhang_tips_on_actual_support_and_falls(app):
    key(app, pygame.K_UP, finish=False)
    assert app.animation.fall_support == (Position(1, 1),)
    source = block_meshes(app.session.state.block)[0]
    app.update(ROLL_MS + FALL_MS / 4)
    mesh = app.animation.frame_meshes()[0][0]
    supported = [i for i, point in enumerate(source.vertices) if point[1] >= 1]
    assert all(mesh.vertices[i][2] >= BLOCK_INSET for i in supported)
    assert any(p[2] < BLOCK_INSET for p in mesh.vertices)
    app.draw()
    app.update(FALL_MS * 0.55)
    assert max(p[2] for p in app.animation.frame_meshes()[0][0].vertices) < 0
    app.draw()
    app.update(2000)
    assert app.animation.block_hidden
    assert app.status_text()[0] == "Try again"
    click(app, "restart")
    assert app.can_play


def test_load_level_and_invalid_file_preserve_session(app, tmp_path):
    missing = tmp_path / "missing.json"
    key(app, pygame.K_RIGHT)
    state, level = app.session.state, app.session.level
    app.handle_event(pygame.event.Event(pygame.DROPFILE, file=str(missing)))
    assert app.error
    assert app.session.state == state
    assert app.session.level == level
    path = tmp_path / "custom.json"
    path.write_text('{"id":"custom","name":"Custom stage","grid":["S..G"]}')
    app.handle_event(pygame.event.Event(pygame.DROPFILE, file=str(path)))
    assert app.session.level.id == "custom"
    assert app.session.action_count == 0
    assert not app.error


def test_path_dialog_handles_text_without_moving_the_block(app, tmp_path):
    path = tmp_path / "custom.json"
    path.write_text('{"id":"custom","name":"Custom stage","grid":["S..G"]}')
    key(app, pygame.K_o)
    app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text=str(path)))
    key(app, pygame.K_RIGHT)
    assert app.session.action_count == 0
    app.draw()
    key(app, pygame.K_RETURN)
    assert app.path_input is None
    assert app.session.level.id == "custom"
    key(app, pygame.K_o)
    key(app, pygame.K_ESCAPE)
    assert app.path_input is None
    assert app.running


@pytest.mark.parametrize("size", [(900, 740), (600, 400), (1500, 800)])
def test_resize_preserves_mouse_coordinates(app, size):
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=size[0], h=size[1]))
    click(app, "right")
    assert app.session.roll_count == 1
    app.update(ROLL_MS)
    click(app, "restart")
    assert app.session.roll_count == 0


def test_real_event_loop_exits_cleanly(app):
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    assert app.run() == 0
    assert not app.running
    assert not app.animation.is_animating
    assert not pygame.display.get_init()


def test_duplicate_levels_advance_from_the_active_entry(app):
    app.levels = [app.levels[0], app.levels[0], app.levels[1]]
    app.selected_index = 1
    app.start_selected_level()
    for _ in range(4):
        key(app, pygame.K_RIGHT)
    assert app.can_advance
    click(app, "next")
    assert app.active_index == 2
    assert app.session.level.id == "02_light_touch"


def test_click_in_letterbox_does_not_trigger_controls(app):
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=1500, h=800))
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(0, 0)))
    assert app.session.action_count == 0
    assert app.selected_index == 0
