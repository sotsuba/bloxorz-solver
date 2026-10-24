"""Pointer integration checks for the native control panel."""

import pygame
import pytest

from bloxorz_solver.game.session import SessionStatus
from bloxorz_solver.ui.app import GameApp


@pytest.fixture
def native_app():
    app = GameApp()
    yield app
    app.close()
    pygame.quit()


def drain(app):
    for _ in range(8):
        for event in pygame.event.get():
            app.handle_event(event)
        app.view.update(16)


def reveal(app, widget):
    sidebar = app.view.sidebar
    bar = sidebar.vert_scroll_bar
    if bar:
        height = sidebar.scrollable_container.rect.height
        target = max(0, min(height - sidebar.rect.height, widget.relative_rect.y - 60))
        bar.set_scroll_from_start_percentage(target / height)
        app.view.update(16)
    assert sidebar.rect.contains(widget.rect)


def click(app, widget):
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        app.handle_event(pygame.event.Event(kind, button=1, pos=widget.rect.center))
    drain(app)


def choose(app, name, value):
    app.draw()
    menu = app.view.dropdowns[name]
    reveal(app, menu)
    click(app, menu)
    assert menu.is_open
    listing = menu.current_state.options_selection_list
    item = next(item for item in listing.item_list if item['object_id'] == value)
    if item['button_element'] is None or not listing.rect.contains(item['button_element'].rect):
        index = listing.item_list.index(item)
        listing.scroll_bar.set_scroll_from_start_percentage(index / len(listing.item_list))
        app.view.update(16)
    click(app, item['button_element'])
    assert not menu.is_open
    app.update(0)


@pytest.mark.parametrize('size', [(800, 600), (1160, 800), (1500, 900), (2320, 1600)])
def test_native_selectors_and_layout(native_app, size):
    app = native_app
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=size[0], h=size[1]))
    for mode in ('DFS', 'UCS', 'A*', 'BFS', 'Manual'):
        choose(app, 'mode', mode)
        assert app.mode == mode
        assert bool(app.view.widgets['solve'].visible) == (mode != 'Manual')
        assert bool(app.view.dropdowns['heuristic'].visible) == (mode == 'A*')
    choose(app, 'stage', '1')
    assert app.active_index == 1
    app.draw()
    assert not app.view.board_rect.colliderect(app.view.panel_rect)
    assert app.screen.get_rect().contains(app.view.board_rect)
    assert app.screen.get_rect().contains(app.view.panel_rect)
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
    assert app.session.roll_count == 1


def test_native_playback_and_next_stage(native_app):
    app = native_app
    choose(app, 'mode', 'A*')
    choose(app, 'heuristic', 'euclidean')
    assert app.heuristic_name == 'euclidean'
    choose(app, 'speed', '2.0')
    assert app.playback_speed == 2
    click(app, app.view.widgets['solve'])
    app._search_future.result(timeout=5)
    app.update(0)
    assert app.solution_completed == 1
    click(app, app.view.widgets['playback'])
    assert not app.autoplay
    app.update(2000)
    before = app.solution_completed
    click(app, app.view.widgets['step'])
    assert app.solution_completed == before + 1
    app.update(2000)
    assert not app.autoplay
    click(app, app.view.widgets['playback'])
    for _ in range(8):
        app.update(2000)
    assert app.session.status is SessionStatus.WON
    app.draw()
    click(app, app.view.result_buttons['next'])
    assert app.active_index == 1


def test_native_sync_does_not_generate_event_storm(native_app):
    app = native_app
    app.draw()
    drain(app)
    pygame.event.clear()
    for _ in range(100):
        app._sync_view()
    assert not pygame.event.get()
    assert app.view.sidebar.visible


