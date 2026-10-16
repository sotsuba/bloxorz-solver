"""Pygame application: events, stage selection, and manual-play controls."""

from collections.abc import Sequence
from functools import partial
from pathlib import Path

import pygame

from bloxorz_solver.game.rules import ROLLS
from bloxorz_solver.game.session import GameSession, SessionStatus
from bloxorz_solver.game.state import Action, EventType, Level, Outcome, SplitBlock
from bloxorz_solver.levels.loader import LevelFormatError, builtin_levels, load_level
from bloxorz_solver.ui.animation import BoardAnimation
from bloxorz_solver.ui.board import Board
from bloxorz_solver.ui.view import CANVAS_SIZE, Button, GameView, create_buttons

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


LOSS_MESSAGES = {
    "out_of_bounds": "The block rolled off the board.",
    "unsupported": "Part of the block has no floor beneath it.",
    "fragile": "The upright block broke a fragile tile.",
}

EVENT_MESSAGES = {
    EventType.BLOCK_SPLIT: "Two cubes now. Press Space to switch control.",
    EventType.BLOCK_MERGED: "Back together. Reach the goal standing upright.",
    EventType.BRIDGE_OPENED: "Bridge opened. Turquoise tiles are safe to cross.",
    EventType.BRIDGE_CLOSED: "Bridge closed. Avoid the dashed turquoise cells.",
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
        pygame.display.set_caption("Bloxorz Solver - Manual play")
        self.view = GameView()
        self.active_index = 0
        self.selected_index = 0
        self.session = GameSession(self.levels[0])
        self.animation = BoardAnimation(self.session.level, self.session.state)
        self.board = Board(self.animation)
        self.running = True
        self.path_input: str | None = None
        self.error = ""
        callbacks = {
            "previous": partial(self.select_level, -1),
            "following": partial(self.select_level, 1),
            "new_game": self.start_selected_level,
            "open": self._open_path_input,
            "swap": partial(self.play, Action.SWAP_ACTIVE_CUBE),
            "restart": self.restart,
            "next": self.next_stage,
            **{action.value: partial(self.play, action) for action in ROLLS},
        }
        self.buttons = create_buttons(callbacks)
        self._key_commands = {
            pygame.K_r: self.restart,
            pygame.K_n: self.next_stage,
            pygame.K_PAGEUP: callbacks["previous"],
            pygame.K_PAGEDOWN: callbacks["following"],
            pygame.K_RETURN: self.start_selected_level,
            pygame.K_o: self._open_path_input,
            pygame.K_ESCAPE: self.close,
        }
        self._display_session()

    @property
    def can_play(self) -> bool:
        return self.session.status is SessionStatus.PLAYING and not self.animation.is_animating

    @property
    def can_advance(self) -> bool:
        return (
            self.session.status is SessionStatus.WON
            and not self.animation.is_animating
            and self.active_index + 1 < len(self.levels)
        )

    def _display_session(self) -> None:
        self.animation.display(
            self.session.level,
            self.session.state,
            lost=self.session.status is SessionStatus.LOST,
            won=self.session.status is SessionStatus.WON,
        )

    def play(self, action: Action) -> None:
        if not self.can_play:
            return
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

    def restart(self) -> None:
        self.session.restart()
        self._display_session()
        self.error = ""

    def select_level(self, offset: int) -> None:
        self.selected_index = (self.selected_index + offset) % len(self.levels)

    def start_selected_level(self) -> None:
        self.active_index = self.selected_index
        self.session = GameSession(self.levels[self.selected_index])
        self._display_session()
        self.error = ""

    def next_stage(self) -> None:
        if self.can_advance:
            self.selected_index = self.active_index + 1
            self.start_selected_level()

    def open_level(self, path: str | Path) -> bool:
        """Validate first, so a bad file cannot discard the active game."""
        try:
            level = load_level(Path(path).expanduser())
        except LevelFormatError as exc:
            self.error = str(exc)
            return False
        self.levels.append(level)
        self.selected_index = len(self.levels) - 1
        self.start_selected_level()
        self._close_path_input()
        return True

    def _open_path_input(self) -> None:
        self.path_input = ""
        self.error = ""
        pygame.key.start_text_input()

    def _close_path_input(self) -> None:
        self.path_input = None
        pygame.key.stop_text_input()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.close()
        elif event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode(
                (max(320, event.w), max(240, event.h)), pygame.RESIZABLE
            )
        elif event.type == pygame.DROPFILE:
            self.open_level(event.file)
        elif self.path_input is not None:
            self._handle_path_event(event)
        elif event.type == pygame.KEYDOWN:
            self._handle_key(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_click(event.pos)

    def _handle_path_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.TEXTINPUT:
            self.path_input += event.text
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._close_path_input()
            elif event.key == pygame.K_BACKSPACE:
                self.path_input = self.path_input[:-1]
            elif event.key == pygame.K_RETURN and self.path_input.strip():
                self.open_level(self.path_input.strip())

    def _handle_key(self, key: int) -> None:
        if key in KEY_ACTIONS:
            self.play(KEY_ACTIONS[key])
            return
        if command := self._key_commands.get(key):
            command()

    def _handle_click(self, position: tuple[int, int]) -> None:
        pos = self.view.canvas_position(self.screen, position)
        if pos is None:
            return
        for button in self._controls().values():
            if button.enabled and button.rect.collidepoint(pos):
                button.callback()
                return

    def _controls(self) -> dict[str, Button]:
        """Refresh only availability, including between events in the same frame."""
        for action in ROLLS:
            self.buttons[action.value].enabled = self.can_play
        self.buttons["swap"].enabled = self.can_play and isinstance(
            self.session.state.block, SplitBlock
        )
        self.buttons["next"].enabled = self.can_advance
        return self.buttons

    def status_text(self) -> tuple[str, str]:
        if self.error:
            return "Cannot load level", self.error
        if self.animation.is_animating:
            return "In motion", "Wait for the block to settle. You can restart at any time."
        if self.session.status is SessionStatus.WON:
            return (
                "Stage complete",
                f"Home in {self.session.roll_count} rolls. Choose another stage or restart.",
            )
        result = self.session.last_result
        if self.session.status is SessionStatus.LOST:
            return "Try again", LOSS_MESSAGES.get(
                result.reason, "The block fell."
            ) + " Press R to restart."
        if result and result.outcome is Outcome.INVALID:
            return "Keep going", "Switching cubes is available after the block splits."
        if result:
            for event in reversed(result.events):
                if event.kind in EVENT_MESSAGES:
                    return "Keep going", EVENT_MESSAGES[event.kind]
        return (
            "Ready to roll",
            "Keep the whole block on the board. Reach the goal standing upright.",
        )

    def draw(self) -> None:
        self.view.draw(
            self.screen,
            session=self.session,
            active_index=self.active_index,
            selected_level=self.levels[self.selected_index],
            selected_index=self.selected_index,
            level_count=len(self.levels),
            board=self.board,
            buttons=list(self._controls().values()),
            status=self.status_text(),
            path_input=self.path_input,
            error=self.error,
        )

    def update(self, elapsed_ms: float) -> None:
        self.animation.update(elapsed_ms)

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
        self.animation.cancel_animation()
        self._close_path_input()
