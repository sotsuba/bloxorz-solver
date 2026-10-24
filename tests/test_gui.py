"""Headless integration tests using actual Pygame surfaces and input events."""

from concurrent.futures import Future

import pygame
import pygame_gui
import pytest

from bloxorz_solver.game.rules import initial_state
from bloxorz_solver.game.session import SessionStatus
from bloxorz_solver.game.state import NormalBlock, Position, SplitBlock
from bloxorz_solver.solvers.astar import AStarSolver
from bloxorz_solver.solvers.base import SearchResult
from bloxorz_solver.solvers.bfs import BFSSolver
from bloxorz_solver.solvers.dfs import DFSSolver
from bloxorz_solver.solvers.ucs import UCSSolver
from bloxorz_solver.ui.animation import BRIDGE_MS, FALL_MS, ROLL_MS
from bloxorz_solver.ui.app import GameApp
from bloxorz_solver.ui.motion import BLOCK_INSET, block_meshes


@pytest.fixture
def app():
    game = GameApp()
    game.set_mode("Manual")
    game.update(0)
    pygame.event.clear()
    yield game
    game.close()
    pygame.quit()


def key(app, code, *, finish=True):
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=code))
    if finish:
        app.update(2000)


def drain_events(app):
    for _ in range(5):
        events = pygame.event.get()
        if not events:
            break
        for event in events:
            app.handle_event(event)
        app.view.update(16)


def ensure_visible(app, widget):
    if (
        widget.ui_container is app.view.sidebar.get_container()
        and not app.view.sidebar.rect.contains(widget.rect)
    ):
        bar = app.view.sidebar.vert_scroll_bar
        assert bar is not None
        height = app.view.sidebar.scrollable_container.rect.height
        target = max(0, min(height - app.view.sidebar.rect.height, widget.relative_rect.y - 100))
        bar.set_scroll_from_start_percentage(target / height)
        app.view.update(16)


def pointer_click(app, pos):
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos))
    drain_events(app)


def click(app, name):
    app.draw()
    widget = app.view.result_buttons.get(name, app.view.widgets[name])
    ensure_visible(app, widget)
    pointer_click(app, widget.rect.center)


def choose(app, name, value):
    app.draw()
    menu = app.view.dropdowns[name]
    ensure_visible(app, menu)
    pointer_click(app, menu.rect.center)
    assert menu.is_open
    listing = menu.current_state.options_selection_list
    item = next(item for item in listing.item_list if item["object_id"] == value)
    if item["button_element"] is None or not listing.rect.contains(item["button_element"].rect):
        listing.scroll_bar.set_scroll_from_start_percentage(listing.item_list.index(item) / len(listing.item_list))
        app.view.update(16)
    pointer_click(app, item["button_element"].rect.center)
    assert not menu.is_open
    app.update(0)


def test_all_stages_render_and_complete_through_keyboard(app, stage_routes):
    keys = dict(U=pygame.K_UP, D=pygame.K_DOWN, L=pygame.K_LEFT, R=pygame.K_RIGHT, X=pygame.K_SPACE)
    for index, level in enumerate(app.levels):
        app.load_stage(index)
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
    click(app, "restart")
    assert app.can_play
    assert app.session.action_count == 0


def test_motion_blocks_overlapping_keyboard_and_mouse_inputs(app):
    key(app, pygame.K_RIGHT, finish=False)
    state = app.session.state
    key(app, pygame.K_RIGHT, finish=False)
    key(app, pygame.K_SPACE, finish=False)
    key(app, pygame.K_RIGHT, finish=False)
    assert app.session.state == state
    assert app.session.roll_count == 1
    app.update(ROLL_MS)
    assert app.can_play
    key(app, pygame.K_RIGHT, finish=False)
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


def test_stage_selection_loads_immediately_and_cancels_motion(app):
    key(app, pygame.K_RIGHT, finish=False)
    assert app.animation.is_animating
    key(app, pygame.K_PAGEDOWN, finish=False)
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
    app.load_stage(2)
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
    app.load_stage(5)
    before, after = stage_routes["06_bridge_builders"].split("X")
    keys = dict(U=pygame.K_UP, D=pygame.K_DOWN, L=pygame.K_LEFT, R=pygame.K_RIGHT)
    for letter in before:
        key(app, keys[letter])
    assert isinstance(app.session.state.block, SplitBlock)
    key(app, pygame.K_SPACE)
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
    assert app.view.result_title == "You lose!"
    assert not app.can_play
    click(app, "restart")
    assert app.session.state == initial_state(app.session.level)
    assert app.can_play










def test_native_widgets_follow_mode_and_animation_state(app):
    assert isinstance(app.view.widgets["restart"], pygame_gui.elements.UIButton)
    assert not app.view.widgets["solve"].visible
    key(app, pygame.K_RIGHT, finish=False)
    app.set_mode("A*")
    app.draw()
    assert app.view.widgets["solve"].visible
    assert app.view.dropdowns["heuristic"].visible
    assert not app.view.widgets["solve"].is_enabled
    app.update(2000)
    assert app.view.widgets["solve"].is_enabled

@pytest.mark.parametrize("size", [(900, 740), (800, 600), (1500, 900)])
def test_resize_preserves_mouse_coordinates(app, size):
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=size[0], h=size[1]))
    key(app, pygame.K_RIGHT, finish=False)
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
    app.load_stage(1)
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
    assert app.active_index == 0


@pytest.mark.parametrize(
    "mode, option", [("BFS", "bfs"), ("DFS", "dfs"), ("UCS", "ucs"), ("A*", "astar")]
)
@pytest.mark.parametrize("size", [(1160, 800), (800, 600), (1500, 900)])
def test_mode_dropdown_selects_algorithms_and_manual_after_resize(app, size, mode, option):
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=size[0], h=size[1]))
    assert app.mode == "Manual"
    assert not app._controls()["solve"].visible
    choose(app, "mode", mode)
    assert app.mode == mode
    assert not app.view.menu_open
    assert app._controls()["solve"].enabled
    key(app, pygame.K_RIGHT)
    assert app.session.roll_count == 0
    choose(app, "mode", "Manual")
    key(app, pygame.K_RIGHT, finish=False)
    assert app.session.roll_count == 1


def test_mode_dropdown_dismisses_without_triggering_covered_controls(app):
    menu = app.view.dropdowns["mode"]
    menu.current_state.finish()
    menu.current_state = menu.menu_states["expanded"]
    menu.current_state.start()
    key(app, pygame.K_ESCAPE)
    assert app.running
    assert not app.view.menu_open
    menu.current_state.finish()
    menu.current_state = menu.menu_states["expanded"]
    menu.current_state.start()
    pointer_click(app, app.view.board_rect.center)
    assert not app.view.menu_open
    assert app.session.roll_count == 0


@pytest.mark.parametrize(
    "mode, option", [("BFS", "bfs"), ("DFS", "dfs"), ("UCS", "ucs"), ("A*", "astar")]
)
def test_algorithms_solve_from_current_position_with_animated_playback(app, mode, option):
    key(app, pygame.K_RIGHT)
    choose(app, "mode", mode)
    click(app, "solve")
    result = app._search_future.result(timeout=5)
    assert result.path
    app.update(0)
    assert app.animation.is_animating
    assert app.session.roll_count == 2
    assert not app._controls()["solve"].enabled
    key(app, pygame.K_UP, finish=False)
    assert app.session.roll_count == 2
    for _ in range(len(result.path) + 1):
        app.update(2000)
    assert app.session.status is SessionStatus.WON
    assert app.session.action_count == 1 + len(result.path)
    assert app.animation.block_hidden
    assert app.can_advance


@pytest.mark.parametrize("mode", ["BFS", "DFS", "UCS", "A*"])
def test_algorithms_report_an_unsolvable_position_without_changing_it(make_level, mode):
    game = GameApp([make_level(grid=("S#G",), start=(0, 0), goal=(0, 2))])
    try:
        game.set_mode(mode)
        original = game.session.state
        game.solve()
        assert game._search_future.result(timeout=5).path is None
        game.update(0)
        game.draw()
        assert "No solution" in game.error
        assert game.session.state == original
        assert game.can_solve
    finally:
        game.close()
        pygame.quit()


@pytest.mark.parametrize("cancel", ["restart", "manual", "new_game", "close"])
def test_running_search_results_are_ignored_after_cancellation(app, monkeypatch, cancel):
    future = Future()
    future.set_running_or_notify_cancel()
    monkeypatch.setattr(app._executor, "submit", lambda *args: future)
    app.set_mode("BFS")
    app.solve()
    app.draw()
    assert app.buttons["solve"].label == "Searching…"
    assert not app.buttons["solve"].enabled
    if cancel == "manual":
        app.set_mode("Manual")
    elif cancel == "new_game":
        app.select_level(1)
    else:
        getattr(app, cancel)()
    assert future.running()
    future.set_result(SearchResult(["right"] * 4, 0, 0, 0, 4))
    app.update(2000)
    assert app._search_future is None
    assert not app._solution
    assert app.session.roll_count == 0


@pytest.mark.parametrize("cancel", ["restart", "manual", "new_game"])
def test_solution_playback_cancels_between_moves(app, monkeypatch, cancel):
    future = Future()
    future.set_result(SearchResult(["right"] * 4, 0, 0, 0, 4))
    monkeypatch.setattr(app._executor, "submit", lambda *args: future)
    app.set_mode("BFS")
    app.solve()
    app.update(0)
    assert app.session.roll_count == 1
    assert app._solution
    if cancel == "manual":
        app.set_mode("Manual")
    elif cancel == "new_game":
        app.select_level(1)
    else:
        app.restart()
    app.update(2000)
    assert not app._solution
    assert app.session.roll_count == (1 if cancel == "manual" else 0)


def test_solution_playback_uses_split_cube_actions(app, monkeypatch, stage_routes):
    app.load_stage(5)
    actions = dict(U="up", D="down", L="left", R="right", X="swap")
    route = [actions[letter] for letter in stage_routes[app.session.level.id]]
    future = Future()
    future.set_result(SearchResult(route, 0, 0, 0, len(route)))
    monkeypatch.setattr(app._executor, "submit", lambda *args: future)
    app.set_mode("BFS")
    app.solve()
    for _ in range(len(route) + 1):
        app.update(2000)
    assert app.session.status is SessionStatus.WON
    assert app.session.swap_count == 1
    assert app.animation.block_hidden


def test_search_failure_is_reported_and_solve_can_be_retried(app, monkeypatch):
    future = Future()
    future.set_exception(RuntimeError("test search error"))
    monkeypatch.setattr(app._executor, "submit", lambda *args: future)
    app.set_mode("BFS")
    app.solve()
    app.update(0)
    assert app.error == "Search failed: test search error"
    assert app.can_solve


@pytest.mark.parametrize(
    "mode, solver_type",
    [("BFS", BFSSolver), ("DFS", DFSSolver), ("UCS", UCSSolver), ("A*", AStarSolver)],
)
def test_solve_dispatches_to_the_selected_algorithm(app, monkeypatch, mode, solver_type):
    submitted = []

    def search(solver, state):
        submitted.append((solver, state))
        return SearchResult([], 0, 0, 0, 0)

    def submit(search, *args):
        future = Future()
        future.set_result(search(*args))
        return future

    monkeypatch.setattr(solver_type, "solve", search)
    monkeypatch.setattr(app._executor, "submit", submit)
    app.set_mode(mode)
    app.solve()
    solver, state = submitted[0]
    assert isinstance(solver, solver_type)
    assert solver.problem.level == app.session.level
    assert state == app.session.state


@pytest.mark.parametrize("mode", ["DFS", "UCS", "A*"])
def test_switching_algorithm_discards_the_old_search_result(app, monkeypatch, mode):
    future = Future()
    future.set_running_or_notify_cancel()
    monkeypatch.setattr(app._executor, "submit", lambda *args: future)
    app.set_mode("BFS")
    app.solve()
    app.set_mode(mode)
    future.set_result(SearchResult(["right"] * 4, 0, 0, 0, 4))
    app.update(2000)
    assert app.mode == mode
    assert app.can_solve
    assert not app._solution
    assert app.session.action_count == 0


def test_heuristic_selector_and_step_playback(app):
    app.set_mode("A*")
    app.draw()
    assert app.view.dropdowns["heuristic"].visible
    choose(app, "heuristic", "euclidean")
    assert app.heuristic_name == "euclidean"
    app.set_heuristic("relaxed_board")
    click(app, "solve")
    result = app._search_future.result(timeout=5)
    app.update(0)
    assert app.last_result == result
    app.draw()
    app.toggle_playback()
    app.update(2000)
    assert not app.autoplay
    assert app.view.widgets["playback"].text == "Resume"
    for count in range(1, len(result.path)):
        click(app, "step")
        assert app.session.action_count == count + 1
        app.update(2000)
        assert app.session.action_count == count + 1
    assert app.session.status is SessionStatus.WON
    app.draw()


def test_heuristic_change_discards_running_search_and_queued_moves(app, monkeypatch):
    future = Future()
    future.set_running_or_notify_cancel()
    monkeypatch.setattr(app._executor, "submit", lambda *args: future)
    app.set_mode("A*")
    app.solve()
    app.set_heuristic("zero")
    future.set_result(SearchResult(["right"] * 4, 0, 0, 0, 4))
    app.update(2000)
    assert app.session.action_count == 0
    assert app.last_result is None and not app._solution
    app.autoplay = False
    app.solve()
    app.update(0)
    assert app._solution
    app.set_heuristic("relaxed_board")
    assert not app._solution and app.last_result is None
    app.set_mode("Manual")
    app.draw()
    assert not app.view.dropdowns["heuristic"].visible


def test_ui_constructs_heuristic_inside_background_job_from_captured_values(app, monkeypatch):
    jobs = []
    factories = []

    def submit(function, *args):
        jobs.append((function, args))
        return Future()

    from bloxorz_solver.ui import app as module

    original = module.create_heuristic

    def create(name, problem):
        factories.append((name, problem.level))
        return original(name, problem)

    monkeypatch.setattr(app._executor, "submit", submit)
    monkeypatch.setattr(module, "create_heuristic", create)
    app.set_mode("A*")
    app.set_heuristic("relaxed_board")
    app.solve()
    assert not factories  # No preprocessing on the event thread.
    app.set_heuristic("zero")
    function, args = jobs[0]
    assert function(*args).path
    assert factories == [("relaxed_board", app.session.level)]


def test_stage_dropdown_replaces_active_game_and_cancels_motion(app):
    key(app, pygame.K_RIGHT, finish=False)
    choose(app, "stage", "1")
    assert app.active_index == 1 and app.session.level == app.levels[1]
    assert not app.animation.is_animating
    assert app.session.action_count == 0
    assert app.view.dropdowns["stage"].current_state.selected_option_button.text.startswith("02")

def ready_route(app, monkeypatch, route=None):
    route = ["right"] * 4 if route is None else route
    future = Future()
    future.set_result(SearchResult(route, 0.001, 1024, 12, len(route)))
    monkeypatch.setattr(app._executor, "submit", lambda *args: future)
    app.set_mode("A*")
    app.solve()
    app.update(0)
    return route


def test_pause_step_and_resume_keep_progress_without_duplicate_actions(app, monkeypatch):
    ready_route(app, monkeypatch)
    assert app.solution_total == 4 and app.solution_completed == 1
    click(app, "playback")
    assert not app.autoplay
    assert not app._controls()["step"].enabled
    app.update(2000)
    assert app.session.action_count == 1
    assert app.view.widgets["playback"].text == "Resume"
    click(app, "step")
    assert app.solution_completed == 2 and app.session.action_count == 2
    app.update(2000)
    assert app.session.action_count == 2
    click(app, "playback")
    for _ in range(4):
        app.update(2000)
    assert app.session.status is SessionStatus.WON
    assert app.solution_total == app.solution_completed == app.session.action_count == 4
    app.draw()
    assert app.animation.block_hidden


@pytest.mark.parametrize("speed", [0.5, 1.0, 2.0, 4.0])
def test_speed_changes_solution_animation_but_not_manual_moves(app, monkeypatch, speed):
    ready_route(app, monkeypatch)
    app.toggle_playback()
    choose(app, "speed", str(speed))
    app.update(ROLL_MS / (2 * speed))
    assert app.animation.elapsed_ms == pytest.approx(ROLL_MS / 2)
    app.restart()
    app.set_mode("Manual")
    key(app, pygame.K_RIGHT, finish=False)
    app.update(ROLL_MS / 2)
    assert app.animation.elapsed_ms == pytest.approx(ROLL_MS / 2)


@pytest.mark.parametrize("speed", [0.5, 1.0, 2.0, 4.0])
def test_all_speeds_preserve_bridge_split_and_merge_routes(app, monkeypatch, stage_routes, speed):
    app.load_stage(5)
    actions = dict(U="up", D="down", L="left", R="right", X="swap")
    route = [actions[letter] for letter in stage_routes[app.session.level.id]]
    app.set_playback_speed(speed)
    ready_route(app, monkeypatch, route)
    for _ in range(len(route) * 4 + 10):
        app.update(2000)
        if app.animation.block_hidden:
            break
    assert app.session.status is SessionStatus.WON
    assert app.solution_total == app.solution_completed == len(route)
    assert app.session.action_count == len(route) and app.session.swap_count == 1
    assert app.animation.block_hidden and app.can_advance








@pytest.mark.parametrize("size", [(800, 600), (1160, 800), (1500, 900), (2320, 1600)])
def test_responsive_layout_scales_controls_and_keeps_actions_reachable(app, size):
    original_height = app.view.widgets["solve"].font.size("Solve")[1]
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=size[0], h=size[1]))
    choose(app, "mode", "A*")
    app.draw()
    scale = max(1, min(size[0] / 1160, size[1] / 800))
    font_height = app.view.widgets["solve"].font.size("Solve")[1]
    assert font_height > original_height if scale > 1 else font_height == original_height
    assert app.screen.get_rect().contains(app.view.board_rect)
    assert not app.view.board_rect.colliderect(app.view.panel_rect)
    click(app, "restart")
    assert app.view.sidebar.rect.contains(app.view.widgets["restart"].rect)
    key(app, pygame.K_ESCAPE)
    assert app.running
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=1160, h=800))
    assert app.view.widgets["solve"].font.size("Solve")[1] == original_height

def test_terminal_actions_wait_for_animation_and_remain_reachable(app):
    key(app, pygame.K_UP, finish=False)
    app.draw()
    assert not app.view.notice_text
    app.update(2000)
    app.draw()
    assert app.view.result_title == "You lose!"
    assert app.session.status is SessionStatus.LOST
    click(app, "restart")
    for _ in range(4):
        key(app, pygame.K_RIGHT)
    app.draw()
    assert app.view.widgets["next"].visible
    click(app, "next")
    assert app.active_index == 1 and app.can_play

def test_search_only_updates_solve_button_without_status_panel(app, monkeypatch):
    future = Future()
    monkeypatch.setattr(app._executor, "submit", lambda *args: future)
    app.set_mode("BFS")
    app.solve()
    app.update(1500)
    app.draw()
    assert app.view.widgets["solve"].text == "Searching…"
    assert not app.view.widgets["solve"].is_enabled
    assert not hasattr(app.view, "status")
