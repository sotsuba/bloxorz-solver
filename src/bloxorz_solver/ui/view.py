"""Window layout, text, and coordinate transforms for the Pygame interface."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import pygame

from bloxorz_solver.game.session import GameSession
from bloxorz_solver.game.state import Level
from bloxorz_solver.ui.board import Board

CANVAS_SIZE = (1160, 800)
BOARD_SIZE = (800, 620)


BUTTON_LAYOUT = {
    "previous": ((860, 30, 46, 38), "<"),
    "following": ((1090, 30, 46, 38), ">"),
    "new_game": ((860, 140, 276, 40), "New game / Enter"),
    "open": ((860, 192, 276, 36), "Open level / O"),
    "mode": ((860, 296, 276, 40), "Manual  v"),
    "solve": ((860, 348, 276, 40), "Solve"),
    "swap": ((860, 550, 276, 40), "Switch cube / Space"),
    "restart": ((860, 630, 132, 40), "Restart / R"),
    "next": ((1004, 630, 132, 40), "Next / N"),
    "up": ((954, 456, 86, 36), "Up"),
    "left": ((860, 502, 86, 36), "Left"),
    "down": ((954, 502, 86, 36), "Down"),
    "right": ((1048, 502, 86, 36), "Right"),
    "mode_manual": ((860, 338, 276, 36), "Manual"),
    "mode_bfs": ((860, 374, 276, 36), "BFS"),
    "mode_dfs": ((860, 410, 276, 36), "DFS"),
    "mode_ucs": ((860, 446, 276, 36), "UCS"),
    "mode_astar": ((860, 482, 276, 36), "A*"),
}


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    callback: Callable[[], None]
    enabled: bool = True
    visible: bool = True


def create_buttons(callbacks: Mapping[str, Callable[[], None]]) -> dict[str, Button]:
    """Bind application commands to the fixed layout once, outside the frame loop."""
    return {
        name: Button(pygame.Rect(rect), label, callbacks[name])
        for name, (rect, label) in BUTTON_LAYOUT.items()
    }


class GameView:
    """Paint session data without handling input or changing the game."""

    def __init__(self):
        self.canvas = pygame.Surface(CANVAS_SIZE)
        self.board_surface = pygame.Surface(BOARD_SIZE)
        self.fonts = {size: pygame.font.Font(None, size) for size in (20, 23, 32, 64)}

    def _text(self, text, pos, size=23, color="#E4EDF3"):
        self.canvas.blit(self.fonts[size].render(text, True, color), pos)

    def _wrap(self, text, rect, size=23, color="#51697A"):
        """Wrap even long filenames and clip to the allocated text area."""
        font = self.fonts[size]
        old_clip = self.canvas.get_clip()
        self.canvas.set_clip(rect)
        y, line = rect.y, ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and font.size(candidate)[0] > rect.width:
                self._text(line, (rect.x, y), size, color)
                y += font.get_linesize()
                line = ""
            for char in (" " if line else "") + word:
                if font.size(line + char)[0] > rect.width:
                    self._text(line, (rect.x, y), size, color)
                    y += font.get_linesize()
                    line = ""
                line += char
        self._text(line, (rect.x, y), size, color)
        self.canvas.set_clip(old_clip)

    def viewport(self, screen: pygame.Surface) -> pygame.Rect:
        width, height = screen.get_size()
        scale = min(width / CANVAS_SIZE[0], height / CANVAS_SIZE[1])
        rect = pygame.Rect(
            0, 0, max(1, round(CANVAS_SIZE[0] * scale)), max(1, round(CANVAS_SIZE[1] * scale))
        )
        rect.center = screen.get_rect().center
        return rect

    def canvas_position(
        self, screen: pygame.Surface, pos: tuple[int, int]
    ) -> tuple[float, float] | None:
        """Use the same letterboxed viewport for rendering and pointer input."""
        viewport = self.viewport(screen)
        if not viewport.collidepoint(pos):
            return None
        return (
            (pos[0] - viewport.x) * CANVAS_SIZE[0] / viewport.width,
            (pos[1] - viewport.y) * CANVAS_SIZE[1] / viewport.height,
        )

    def draw(
        self,
        screen: pygame.Surface,
        *,
        session: GameSession,
        selected_level: Level,
        selected_index: int,
        level_count: int,
        board: Board,
        buttons: Sequence[Button],
        path_input: str | None,
        error: str,
    ) -> None:
        self.canvas.fill("#172D42")
        pygame.draw.rect(self.canvas, "#F2F6F8", (836, 0, 324, 800))
        self._draw_header(session)
        board.draw(self.board_surface)
        self.canvas.blit(self.board_surface, (18, 102))
        self._text(
            "Orange: fragile    Teal: bridge    Circle: soft    X: heavy    Purple: split",
            (30, 736),
            20,
            "#B9CEDA",
        )
        self._text(
            "Arrows / WASD to roll    Space to switch cubes",
            (30, 768),
            20,
            "#A8BFCE",
        )
        self._draw_sidebar(selected_level, selected_index, level_count, error)
        self._draw_buttons(buttons)
        if path_input is not None:
            self._draw_path_dialog(path_input, error)
        viewport = self.viewport(screen)
        screen.fill("#0F2233")
        screen.blit(pygame.transform.smoothscale(self.canvas, viewport.size), viewport)
        pygame.display.flip()

    def _draw_header(self, session: GameSession) -> None:
        """Align the title and counters on the same vertical center."""
        title = self.fonts[64].render("Bloxorz", True, "#E4EDF3")
        title_rect = title.get_rect(topleft=(28, 24))
        self.canvas.blit(title, title_rect)
        counters = f"{session.roll_count} rolls   {session.swap_count} swaps"
        metrics = self.fonts[23].render(counters, True, "#F0C78C")
        self.canvas.blit(metrics, metrics.get_rect(midright=(818, title_rect.centery)))

    def _draw_sidebar(
        self,
        selected_level: Level,
        selected_index: int,
        level_count: int,
        error: str,
    ) -> None:
        """Group level selection, movement, and session controls in the sidebar."""
        self._text(f"Stage {selected_index + 1:02d} / {level_count:02d}", (935, 41), 23, "#21374B")
        self._wrap(selected_level.name, pygame.Rect(860, 88, 276, 36), color="#21374B")
        self._text("Play mode", (860, 268), 23, "#21374B")
        self._text("Move the block", (860, 428), 23, "#21374B")
        self._text("Drop a JSON file here to load a level.", (860, 694), 20, "#627B8B")
        self._wrap(error, pygame.Rect(860, 724, 276, 64), size=20, color="#A34F38")

    def _draw_buttons(self, buttons: Sequence[Button]) -> None:
        for button in buttons:
            if not button.visible:
                continue
            pygame.draw.rect(
                self.canvas,
                "#DCE8ED" if button.enabled else "#E8EEF1",
                button.rect,
                border_radius=5,
            )
            pygame.draw.rect(self.canvas, "#B7C9D3", button.rect, 1, border_radius=5)
            label = self.fonts[23].render(
                button.label, True, "#21374B" if button.enabled else "#95A6B1"
            )
            self.canvas.blit(label, label.get_rect(center=button.rect.center))

    def _draw_path_dialog(self, path_input: str, error: str) -> None:
        shade = pygame.Surface(CANVAS_SIZE, pygame.SRCALPHA)
        shade.fill((4, 12, 20, 190))
        self.canvas.blit(shade, (0, 0))
        pygame.draw.rect(self.canvas, "#F2F6F8", (180, 260, 800, 280), border_radius=10)
        self._text("Open a JSON level", (208, 284), 32, "#21374B")
        self._text(
            "Type a path, then Enter. Esc cancels. You can also drop a file.",
            (208, 328),
            23,
            "#51697A",
        )
        pygame.draw.rect(self.canvas, "#FFFFFF", (208, 366, 744, 46), border_radius=4)
        field = pygame.Rect(220, 379, 720, 26)
        old_clip = self.canvas.get_clip()
        self.canvas.set_clip(field)
        text_width = self.fonts[23].size(path_input + "|")[0]
        self._text(
            path_input + "|", (min(field.x, field.right - text_width), field.y), color="#21374B"
        )
        self.canvas.set_clip(old_clip)
        self._wrap(error, pygame.Rect(208, 430, 744, 90), size=20, color="#A34F38")
