"""Pygame application: manual play, background search, and solution playback."""

from collections.abc import Sequence
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from copy import copy
from dataclasses import dataclass
from functools import partial
from threading import Event, Lock
from time import perf_counter

import pygame
import pygame_gui

from bloxorz_solver.game.session import GameSession, SessionStatus
from bloxorz_solver.game.state import Action, GameState, Level, Outcome
from bloxorz_solver.levels.loader import builtin_levels
from bloxorz_solver.solvers.astar import AStarSolver
from bloxorz_solver.solvers.base import SearchCancelled, SearchResult, check_cancelled
from bloxorz_solver.solvers.bfs import BFSSolver
from bloxorz_solver.solvers.dfs import DFSSolver
from bloxorz_solver.solvers.heuristics import DEFAULT_HEURISTIC, HEURISTICS, create_heuristic
from bloxorz_solver.solvers.problem import BloxorzProblem
from bloxorz_solver.solvers.ucs import UCSSolver
from bloxorz_solver.ui.animation import BoardAnimation
from bloxorz_solver.ui.board import Board
from bloxorz_solver.ui.playback import Playback, SessionSnapshot, build_snapshots
from bloxorz_solver.ui.view import (
    CANVAS_SIZE,
    MIN_WINDOW_SIZE,
    PLAYBACK_SPEEDS,
    Button,
    GameView,
    create_buttons,
)

SOLVERS = {"BFS": BFSSolver, "DFS": DFSSolver, "UCS": UCSSolver, "A*": AStarSolver}


@dataclass
class UISearchResult(SearchResult):
    initialization_time: float = 0.0
    snapshots: tuple[SessionSnapshot, ...] = ()
    actions: tuple[Action, ...] = ()


def solve_position(level: Level, state: GameState, mode: str, heuristic: str,
                   cancel_event: Event | None = None,
                   session: GameSession | None = None) -> UISearchResult:
    """Build search inputs and reversible snapshots entirely in the worker."""
    check_cancelled(cancel_event)
    started = perf_counter()
    problem = BloxorzProblem(level)
    solver = (
        AStarSolver(problem, create_heuristic(heuristic, problem, cancel_event=cancel_event))
        if mode == "A*"
        else SOLVERS[mode](problem)
    )
    initialization_time = perf_counter() - started
    result = solver.solve(state, cancel_event=cancel_event)
    if session is None:
        session = GameSession(level)
        session.state = state
    snapshots = (build_snapshots(session, result.path, cancel_event)
                 if result.is_found else ())
    check_cancelled(cancel_event)
    return UISearchResult(**vars(result), initialization_time=initialization_time,
                          snapshots=snapshots,
                          actions=tuple(Action(action) for action in (result.path or ())))


KEY_ACTIONS = {
    pygame.K_UP: Action.UP,
    pygame.K_w: Action.UP,
    pygame.K_DOWN: Action.DOWN,
    pygame.K_s: Action.DOWN,
    pygame.K_LEFT: Action.LEFT,
    pygame.K_a: Action.LEFT,
    pygame.K_RIGHT: Action.RIGHT,
    pygame.K_d: Action.RIGHT,
    pygame.K_SPACE: Action.SWAP_ACTIVE_CUBE,
}


class GameApp:
    """Own a session and render it; the session remains independent of Pygame."""

    def __init__(self, levels: Sequence[Level] | None = None):
        self.levels = list(builtin_levels() if levels is None else levels)
        if not self.levels:
            raise ValueError("At least one level is required")
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode(CANVAS_SIZE, pygame.RESIZABLE)
        pygame.display.set_caption("Bloxorz")
        self.view = GameView()
        self.active_index = 0
        self.session = GameSession(self.levels[0])
        self.animation = BoardAnimation(self.session.level, self.session.state)
        self.board = Board(self.animation)
        self.running = True
        self.error = ""
        self.mode = "BFS"
        self.heuristic_name = DEFAULT_HEURISTIC
        self.autoplay = True
        self.playback_speed = 1.0
        self.solution_total = 0
        self.solution_completed = 0
        self._solution_animation = False
        self.last_result: SearchResult | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._search_future: Future[SearchResult] | None = None
        self.playback: Playback | None = None
        self._cancel_event: Event | None = None
        self._request_id = 0
        self._result_lock = Lock()
        self._completed_searches = {}
        self.search_status = "Idle"
        callbacks = {
            "restart": self.restart,
            "next": self.next_stage,
            "solve": self.solve,
            "playback": self.toggle_playback,
            "cancel": self.cancel_search,
            "prev_stage": partial(self.select_level, -1),
            "next_stage": partial(self.select_level, 1),
        }
        self.buttons = create_buttons(callbacks)
        self.view.bind_buttons(self.buttons)
        self._key_commands = {
            pygame.K_r: self.restart,
            pygame.K_n: self.next_stage,
            pygame.K_PAGEUP: partial(self.select_level, -1),
            pygame.K_PAGEDOWN: partial(self.select_level, 1),
        }
        self._display_session()
        self._sync_view()

    @property
    def can_play(self) -> bool:
        return (
            self.mode == "Manual"
            and self.session.status is SessionStatus.PLAYING
            and not self.animation.is_animating
        )

    @property
    def can_solve(self) -> bool:
        """Search only when the active stage is idle and unfinished."""
        return (
            self.mode in SOLVERS
            and self.session.status is SessionStatus.PLAYING
            and not self.animation.is_animating
            and self._search_future is None
            and self.playback is None
        )

    @property
    def can_advance(self) -> bool:
        return (
            self.session.status is SessionStatus.WON
            and not self.animation.is_animating
            and self.active_index + 1 < len(self.levels)
        )

    def _display_session(self) -> None:
        self._solution_animation = False
        self.animation.display(
            self.session.level,
            self.session.state,
            lost=self.session.status is SessionStatus.LOST,
            won=self.session.status is SessionStatus.WON,
        )

    def play(self, action: Action) -> None:
        if not self.can_play:
            return
        self._apply_action(action)

    def _apply_action(self, action: Action) -> None:
        """Commit and animate a move for either the player or solution playback."""
        previous = self.session.state
        result = self.session.apply_action(action)
        if (
            result
            and result.outcome is not Outcome.INVALID
            and action is not Action.SWAP_ACTIVE_CUBE
        ):
            self.animation.animate_move(self.session.level, previous, action, result)
        else:
            self._display_session()
        self.error = ""

    def set_mode(self, mode: str) -> None:
        """Switch control modes without discarding the current board position."""
        if mode == self.mode:
            return
        if mode != "Manual" and mode not in SOLVERS:
            raise ValueError(f"Unknown play mode: {mode}")
        self._cancel_solution()
        self.mode = mode
        self.error = ""

    @property
    def autoplay(self):
        return self.playback.playing if getattr(self, "playback", None) else self._autoplay

    @autoplay.setter
    def autoplay(self, value):
        self._autoplay = value
        if getattr(self, "playback", None):
            self.playback.playing = value

    @property
    def _solution(self):
        """Remaining actions, retained for callers inspecting playback progress."""
        return self.playback.actions[self.playback.index:] if self.playback else ()

    def solve(self) -> None:
        if not self.can_solve:
            return
        self.error = ""
        self.last_result = None
        self.solution_total = self.solution_completed = 0
        self._request_id += 1
        request_id = self._request_id
        event = self._cancel_event = Event()
        captured = copy(self.session)
        self.search_status = "Searching…"
        self._search_future = self._executor.submit(
            solve_position, captured.level, captured.state, self.mode, self.heuristic_name,
            event, captured,
        )
        self._search_future.add_done_callback(
            partial(self._publish_search, request_id, event, captured)
        )

    def _publish_search(self, request_id, event, captured, future):
        """A worker callback publishes plain data; it never calls Pygame."""
        result, snapshots, actions, error = None, (), (), None
        try:
            result = future.result()
            snapshots = getattr(result, "snapshots", ())
            actions = getattr(result, "actions", ())
            if result.is_found and not snapshots:
                snapshots = build_snapshots(captured, result.path, event)
            if result.is_found and not actions:
                actions = tuple(Action(action) for action in result.path)
        except Exception as exc:
            error = exc
        with self._result_lock:
            if not event.is_set():
                self._completed_searches[request_id] = (result, snapshots, actions, error)

    def cancel_search(self):
        if self._search_future is not None:
            self._cancel_solution()
            self.error = ""
            self.search_status = "Cancelled"

    def set_heuristic(self, name: str) -> None:
        if name not in HEURISTICS:
            raise ValueError(f"Unknown built-in heuristic: {name}")
        if name != self.heuristic_name:
            self._cancel_solution()
            self.heuristic_name = name
            self.error = ""

    def set_playback_speed(self, speed: float) -> None:
        if speed not in PLAYBACK_SPEEDS:
            raise ValueError(f"Unsupported playback speed: {speed}")
        self.playback_speed = speed

    def toggle_playback(self) -> None:
        if self.playback:
            if self.playback.playing:
                self.playback.pause()
            else:
                self.playback.play()
            self._sync_progress()

    def _sync_progress(self):
        self.solution_total = len(self.playback.actions) if self.playback else 0
        self.solution_completed = self.playback.index if self.playback else 0
        self._solution_animation = bool(self.playback and self.animation.is_animating)

    def step_solution(self) -> None:
        self.seek_relative(1)

    def seek_relative(self, delta):
        if self.playback:
            self.seek_solution(self.playback.index + delta)

    def seek_solution(self, index):
        if self.playback and not self.view.menu_open:
            self.view.clear_result()
            self.playback.seek(index)
            self._sync_progress()
            self._sync_view()

    def jump_to_end(self):
        if self.playback:
            self.seek_solution(len(self.playback.actions))

    def _cancel_solution(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._search_future is not None:
            self._search_future.cancel()
            self._search_future = None
        with self._result_lock:
            self._completed_searches.clear()
        self.playback = None
        self._autoplay = True
        self._sync_progress()
        self.last_result = None
        self.search_status = "Idle"

    def _update_solution(self) -> None:
        with self._result_lock:
            completed = self._completed_searches.pop(self._request_id, None)
        if completed is None:
            return
        self._search_future = None
        result, snapshots, actions, error = completed
        if isinstance(error, (CancelledError, SearchCancelled)):
            self.search_status = "Cancelled"
        elif error:
            self.error = f"Search failed: {error}"
            self.search_status = "Error"
            self.view.show_notice("Search failed")
        else:
            self.last_result = result
            if not result.is_found:
                self.error = "No solution from this position."
                self.search_status = "No solution"
                self.view.show_notice("No solution found")
            else:
                self.search_status = "Solved"
                self.playback = Playback(self.session, self.animation, actions, snapshots)

    def restart(self) -> None:
        self.view.clear_result()
        self.view.show_notice("")
        self.view.dismiss_menus()
        self._cancel_solution()
        self.session.restart()
        self._display_session()
        self.error = ""

    def select_level(self, offset: int) -> None:
        index = self.active_index + offset
        if 0 <= index < len(self.levels):
            self.load_stage(index)

    def load_stage(self, index: int) -> None:
        self.view.clear_result()
        self.view.show_notice("")
        self.view.dismiss_menus()
        self._cancel_solution()
        self.active_index = index
        self.session = GameSession(self.levels[index])
        self._display_session()
        self.error = ""

    def next_stage(self) -> None:
        if self.can_advance:
            self.load_stage(self.active_index + 1)

    def handle_event(self, event: pygame.event.Event) -> None:
        self._sync_view()
        if event.type == pygame.QUIT:
            self.close()
            return
        if event.type in (pygame.VIDEORESIZE, pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED):
            width = event.dict.get("w", event.dict.get("x", self.view.size[0]))
            height = event.dict.get("h", event.dict.get("y", self.view.size[1]))
            size = (max(MIN_WINDOW_SIZE[0], width), max(MIN_WINDOW_SIZE[1], height))
            current = pygame.display.get_surface()
            if size == self.view.size and current.get_size() == size:
                return
            # SDL may already have resized the display surface. Reuse it so a
            # native maximize does not unnecessarily recreate the window.
            self.screen = (current if current.get_size() == size else
                           pygame.display.set_mode(size, pygame.RESIZABLE))
            self.view.resize(size)
            return
        if self.view.result_open:
            self.view.process_event(event)
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                for name, widget in self.view.result_buttons.items():
                    if event.ui_element is widget:
                        self.buttons[name].callback()
                        break
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    self.restart()
                elif event.key == pygame.K_n:
                    self.next_stage()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.view.dismiss_menus()
            return
        # A click outside an expanded menu dismisses it without activating controls below.
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.view.menu_open
        ):
            if not any(
                menu.contains_pointer(event.pos)
                for menu in self.view.dropdowns.values()
                if menu.is_open
            ):
                self.view.dismiss_menus()
                return
        consumed = self.view.process_event(event)
        if event.type == pygame_gui.UI_DROP_DOWN_MENU_CHANGED:
            self._handle_selection(event)
        elif event.type == pygame_gui.UI_BUTTON_PRESSED:
            for name, widget in self.view.widgets.items():
                if event.ui_element is widget:
                    button = self._controls()[name]
                    if button.visible and button.enabled and not self.view.menu_open:
                        button.callback()
                    break
        elif event.type == pygame.KEYDOWN and not consumed and not self.view.menu_open:
            self._handle_key(event.key)

    def _handle_selection(self, event: pygame.event.Event) -> None:
        value = getattr(event, "selected_option_id", event.text)
        menus = self.view.dropdowns
        if event.ui_element is menus["stage"]:
            self.load_stage(int(value))
        elif event.ui_element is menus["mode"]:
            self.set_mode(value)
        elif event.ui_element is menus["heuristic"]:
            self.set_heuristic(value)

    def _handle_key(self, key: int) -> None:
        if key in KEY_ACTIONS:
            self.play(KEY_ACTIONS[key])
        elif command := self._key_commands.get(key):
            command()

    def _controls(self) -> dict[str, Button]:
        solver = self.mode in SOLVERS
        playback = solver and self.playback is not None
        self.buttons["next"].visible = self.can_advance
        self.buttons["next"].enabled = self.can_advance
        self.buttons["prev_stage"].enabled = self.active_index > 0
        self.buttons["next_stage"].enabled = self.active_index + 1 < len(self.levels)
        self.buttons["solve"].visible = solver
        self.buttons["solve"].enabled = self.can_solve
        self.buttons["solve"].label = "Searching…" if self._search_future else "Solve"
        self.buttons["cancel"].visible = self._search_future is not None
        self.buttons["cancel"].enabled = self._search_future is not None
        for name in ("playback",):
            self.buttons[name].visible = playback
            self.buttons[name].enabled = playback and bool(self.playback.actions)
        self.buttons["playback"].label = "⏸" if playback and self.autoplay else "⏯"
        return self.buttons

    def _sync_view(self) -> None:
        self.view.configure(
            self.levels, self.active_index, self.mode,
            self.heuristic_name,
        )
        self.view.sync_buttons(self._controls())
        self.view.sync_metrics(self.last_result)
        status = "Solved" if self.session.status is SessionStatus.WON else self.search_status
        if self.view.status.text != status:
            self.view.status.set_text(status)

    def draw(self) -> None:
        self._sync_view()
        self.view.draw(self.screen, board=self.board)

    def update(self, elapsed_ms: float) -> None:
        elapsed_ms = max(0, elapsed_ms)
        self.animation.visual_time = getattr(self.animation, "visual_time", 0) + elapsed_ms / 1000
        self._update_solution()
        if self.playback:
            if not self.view.menu_open:
                self.playback.update(elapsed_ms / 1000, self.playback_speed)
            self._sync_progress()
        else:
            self.animation.update(elapsed_ms)
        if (self.session.status is not SessionStatus.PLAYING and
                not self.animation.is_animating and not self.view.result_open):
            self.view.show_result(won=self.session.status is SessionStatus.WON,
                                  can_advance=self.can_advance)
        self._sync_view()
        self.view.update(elapsed_ms)

    def run(self) -> int:
        clock = pygame.time.Clock()
        try:
            while self.running:
                elapsed = clock.tick(60)
                # Advance existing motion before processing new moves in this frame.
                self.update(elapsed)
                for event in pygame.event.get():
                    self.handle_event(event)
                    if not self.running:
                        break
                if self.running:
                    self.draw()
            return 0
        finally:
            self.close()
            pygame.quit()

    def close(self) -> None:
        self.running = False
        self._cancel_solution()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.animation.cancel_animation()
