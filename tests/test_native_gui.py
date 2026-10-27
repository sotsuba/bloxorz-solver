"""Pointer integration checks for the native control panel."""

import pygame
import pygame_gui
import pytest

from bloxorz_solver.game.session import SessionStatus
from bloxorz_solver.solvers.base import SearchResult
from bloxorz_solver.ui.app import GameApp


@pytest.fixture
def native_app():
    app = GameApp()
    yield app
    app.close()
    pygame.quit()


@pytest.mark.parametrize("size", [(800, 600), (1160, 800), (2320, 1600)])
def test_search_metrics_display_and_layout(native_app, size):
    app = native_app
    app.view.resize(size)
    app.draw()
    labels = app.view.metric_labels
    assert labels["search_time"].text == "Search time: —"
    app.last_result = SearchResult(["right"], 0.0125, 2048, 1234, 1)
    app.draw()
    assert labels["search_time"].text == "Search time: 12.50 ms"
    assert labels["peak_memory"].text == "Peak memory: 0.002 MB"
    assert labels["expanded_nodes"].text == "Expanded nodes: 1,234"
    assert labels["solution_length"].text == "Solution length: 1"
    previous = app.view.widgets["restart"]
    for label in labels.values():
        assert label.relative_rect.top >= previous.relative_rect.bottom
        assert label.relative_rect.right <= app.view.sidebar.rect.width - 20
        reveal(app, label)
        previous = label
    app.restart()
    app.draw()
    assert labels["peak_memory"].text == "Peak memory: —"
    app.set_mode("Manual")
    app.draw()
    assert all(not label.visible for label in labels.values())


def test_search_metrics_no_solution_and_empty_solution(native_app):
    app = native_app
    app.last_result = SearchResult(None, 1.5, 2 * 1024**2, 42, 0)
    app.draw()
    labels = app.view.metric_labels
    assert labels["search_time"].text == "Search time: 1,500.00 ms"
    assert labels["peak_memory"].text == "Peak memory: 2.097 MB"
    assert labels["expanded_nodes"].text == "Expanded nodes: 42"
    assert labels["solution_length"].text == "Solution length: —"
    app.last_result = SearchResult([], 0, 0, 0, 0)
    app.draw()
    assert labels["solution_length"].text == "Solution length: 0"
    assert labels["search_time"].text == "Search time: 0.00 ms"


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
    assert 'speed' not in app.view.dropdowns
    assert app.playback_speed == 1
    click(app, app.view.widgets['solve'])
    app._search_future.result(timeout=5)
    app.update(0)
    assert app.solution_completed == 1
    click(app, app.view.widgets['playback'])
    assert not app.autoplay
    app.update(2000)
    assert not app.autoplay
    click(app, app.view.widgets['playback'])
    for _ in range(8):
        app.update(2000)
    assert app.session.status is SessionStatus.WON
    app.draw()
    assert app.view.result_title == "You win!"
    app.view.update(16)
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




def test_simplified_playback_and_restart(native_app):
    app = native_app
    app.solve()
    app._search_future.result(timeout=5)
    app.update(0)
    app.draw()
    assert app.view.widgets['playback'].visible
    assert not {'start', 'back', 'step', 'end'} & app.view.widgets.keys()
    assert not hasattr(app.view, 'scrubber')
    app.restart()
    app.update(0)
    assert app.playback is None and app.last_result is None
    assert app.view.status.text == 'Idle'
    assert app.view.metric_labels['search_time'].text == 'Search time: —'
    assert not app.view.widgets['playback'].visible



def test_live_search_cancel_keeps_event_loop_responsive_and_can_retry(native_app, monkeypatch):
    from threading import Event
    from time import perf_counter

    from bloxorz_solver.solvers.base import SearchCancelled
    from bloxorz_solver.solvers.contracts import Transition
    from bloxorz_solver.solvers.problem import BloxorzProblem

    app = native_app
    started = Event()
    sequence = iter(range(1, 10**9))
    original = BloxorzProblem.get_successors

    def endless(self, state):
        started.set()
        yield Transition('right', next(sequence))

    monkeypatch.setattr(BloxorzProblem, 'get_successors', endless)
    app.solve()
    future = app._search_future
    assert started.wait(2)
    began = perf_counter()
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=800, h=600))
    app.update(16)
    app.draw()
    assert app.view.status.text == 'Searching…'
    assert not app.view.widgets['solve'].is_enabled
    reveal(app, app.view.widgets['cancel'])
    click(app, app.view.widgets['cancel'])
    assert perf_counter() - began < 1
    with pytest.raises(SearchCancelled):
        future.result(timeout=2)
    app.update(0)
    assert app.view.status.text == 'Cancelled'
    assert app.last_result is None and app.can_solve
    assert not app._completed_searches
    monkeypatch.setattr(BloxorzProblem, 'get_successors', original)
    app.solve()
    app._search_future.result(timeout=5)
    app.update(0)
    assert app.view.status.text == 'Solved' and app.playback


@pytest.mark.parametrize('size', [(800, 600), (1160, 800), (1920, 1080)])
def test_every_stage_fits_and_cards_stay_inside_sidebar(native_app, size):
    from bloxorz_solver.ui.rendering import to_screen

    app = native_app
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=size[0], h=size[1]))
    for index in range(len(app.levels)):
        app.load_stage(index)
        app.update(0)
        app.draw()
        rect = app.view.board_surface.get_rect()
        level = app.session.level
        for col in (-1, level.width + 1):
            for row in (-1, level.height + 1):
                for height in (-1, 2):
                    point = to_screen(col, row, height, app.board._view)
                    assert rect.collidepoint(point)
        cards = sorted((card for card in app.view.cards.values() if card.visible),
                       key=lambda card: card.relative_rect.top)
        for previous, following in zip(cards, cards[1:], strict=False):
            assert following.relative_rect.top - previous.relative_rect.bottom >= 16
        for card in cards:
            assert card.relative_rect.right <= app.view.sidebar.rect.width - 20


def test_render_uses_cached_fonts_and_transport_glyphs(native_app, monkeypatch):
    app = native_app
    app.load_stage(5)
    app.draw()
    fonts = app.board._label_fonts.copy()

    def unexpected(*args, **kwargs):
        raise AssertionError('Font allocated during rendering')

    monkeypatch.setattr(pygame.font, 'Font', unexpected)
    for _ in range(3):
        app.update(16)
        app.draw()
    assert app.board._label_fonts == fonts
    # The bundled symbol font covers every transport glyph rather than displaying tofu.
    from pathlib import Path

    from pygame import freetype

    freetype.init()
    font = freetype.Font(
        str(Path(__file__).parents[1] /
            'src/bloxorz_solver/ui/fonts/NotoSansSymbols2-Regular.ttf'), 18,
    )
    assert all(metric is not None for metric in font.get_metrics('⏮◀⏯⏸▶⏭'))


@pytest.mark.parametrize("event_type", [pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED])
def test_native_window_resize_events_relayout_without_duplicate_rebuild(native_app, event_type,
                                                                         monkeypatch):
    app = native_app
    app.handle_event(pygame.event.Event(event_type, x=900, y=650))
    assert app.view.size == app.screen.get_size() == (900, 650)
    assert app.screen.get_rect().contains(app.view.board_rect)
    def unexpected(*args):
        raise AssertionError("Duplicate resize rebuilt the UI")
    monkeypatch.setattr(app.view, "resize", unexpected)
    app.handle_event(pygame.event.Event(event_type, x=900, y=650))
