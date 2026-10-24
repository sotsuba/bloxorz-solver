"""Rendering caches must preserve live animation and reset with board geometry."""

import pygame
import pytest

from bloxorz_solver.ui.animation import BRIDGE_MS, FALL_MS, ROLL_MS
from bloxorz_solver.ui.app import GameApp
from bloxorz_solver.ui.board import Board


@pytest.fixture
def game():
    app = GameApp()
    app.set_mode("Manual")
    yield app
    app.close()
    pygame.quit()


def render(app):
    surface = app.view.board_surface
    app.board.draw(surface)
    reference = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    Board(app.animation).draw(reference)
    assert pygame.image.tobytes(surface, "RGBA") == pygame.image.tobytes(reference, "RGBA")


def move(app, key, elapsed=2000):
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
    app.update(elapsed)


def test_platform_is_reused_through_roll_and_restart(game, monkeypatch):
    calls = []
    original = game.board._draw_platform

    def draw(size):
        calls.append(size)
        return original(size)

    monkeypatch.setattr(game.board, "_draw_platform", draw)
    render(game)
    scratch = game.board._block_layer
    for elapsed in (0, ROLL_MS / 2, ROLL_MS):
        if elapsed == 0:
            move(game, pygame.K_RIGHT, 0)
        else:
            game.update(elapsed)
        render(game)
    game.restart()
    render(game)
    assert len(calls) == 1
    assert game.board._block_layer is scratch
    game.load_stage(1)
    render(game)
    assert len(calls) == 2
    game.view.resize((800, 600))
    render(game)
    assert len(calls) == 3
    assert game.board._block_layer is not scratch


def test_bridge_animation_and_restart_invalidate_platform(game):
    game.load_stage(2)
    move(game, pygame.K_UP)
    move(game, pygame.K_RIGHT)
    render(game)
    closed = game.board._platform
    move(game, pygame.K_RIGHT, ROLL_MS + BRIDGE_MS / 2)
    render(game)
    halfway = game.board._platform
    assert halfway is not closed
    game.update(BRIDGE_MS)
    render(game)
    opened = game.board._platform
    assert opened is not halfway
    game.update(0)
    render(game)
    assert game.board._platform is opened
    game.restart()
    render(game)
    assert game.board._platform is not opened
    assert game.animation.bridge_openness("crossing") == 0


def test_loss_mask_and_scratch_layers_are_reused_without_stale_pixels(game):
    move(game, pygame.K_UP, ROLL_MS + FALL_MS / 4)
    render(game)
    mask, scratch = game.board._occlusion, game.board._below_layer
    assert mask is not None
    game.update(FALL_MS / 4)
    render(game)
    assert game.board._occlusion is mask
    assert game.board._below_layer is scratch
    game.restart()
    render(game)
    move(game, pygame.K_RIGHT, ROLL_MS / 2)
    render(game)
    game.load_stage(1)
    render(game)
    assert game.board._occlusion is None


def test_cached_frames_match_fresh_render_through_split_and_merge(game, stage_routes):
    game.load_stage(5)
    keys = dict(U=pygame.K_UP, D=pygame.K_DOWN, L=pygame.K_LEFT,
                R=pygame.K_RIGHT, X=pygame.K_SPACE)
    for letter in stage_routes[game.session.level.id]:
        move(game, keys[letter], ROLL_MS / 2)
        render(game)
        game.update(ROLL_MS / 2 + 90)
        render(game)
        game.update(2000)
        render(game)
