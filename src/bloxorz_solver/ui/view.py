"""Native solver controls alongside the shared game background."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pygame
import pygame_gui
from pygame_gui.elements import UIButton, UIDropDownMenu, UILabel, UIScrollingContainer, UIWindow

from bloxorz_solver.game.state import Level
from bloxorz_solver.solvers.heuristics import HEURISTICS
from bloxorz_solver.ui.board import Board

CANVAS_SIZE = (1160, 800)
MIN_WINDOW_SIZE = (800, 600)
SIDEBAR_WIDTH = 300
PLAYBACK_SPEEDS = (0.5, 1.0, 2.0, 4.0)
NOTICE_MS = 1800
NOTICE_FADE_MS = 800
MODES = ("Manual", "BFS", "DFS", "UCS", "A*")
BUTTON_LABELS = {
    "solve": "Solve", "restart": "Restart", "next": "Next",
    "playback": "Pause", "step": "Step",
}


@dataclass
class Button:
    label: str
    callback: Callable[[], None]
    enabled: bool = True
    visible: bool = True


def create_buttons(callbacks: Mapping[str, Callable[[], None]]) -> dict[str, Button]:
    return {name: Button(label, callbacks[name]) for name, label in BUTTON_LABELS.items()}


class Dropdown(UIDropDownMenu):
    """Small adapter for programmatic selection and dismissal in pygame_gui 0.6."""

    _dropped_selection = False

    @property
    def is_open(self) -> bool:
        return self.current_state is self.menu_states["expanded"]

    def dismiss(self) -> None:
        if self.is_open:
            self._switch_to_closed_state()

    def select(self, option: tuple[str, str]) -> None:
        if self.selected_option != option:
            self.selected_option = option
            self._switch_to_closed_state()

    def contains_pointer(self, pos: tuple[int, int]) -> bool:
        if self.rect.collidepoint(pos):
            return True
        listing = getattr(self.current_state, "options_selection_list", None)
        return listing is not None and listing.rect.collidepoint(pos)

    def process_event(self, event: pygame.event.Event) -> bool:
        listing = getattr(self.current_state, "options_selection_list", None)
        if (
            event.type == pygame_gui.UI_SELECTION_LIST_DROPPED_SELECTION
            and event.ui_element is listing
            and event.text == self.selected_option[0]
        ):
            self._dropped_selection = True
        elif (
            event.type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION and event.ui_element is listing
        ):
            self._dropped_selection = False
        return super().process_event(event)

    def update(self, time_delta: float):
        super().update(time_delta)
        if self._dropped_selection:
            self._dropped_selection = False
            self.dismiss()


class GameView:
    """Keep controls in a responsive, scrollable panel beside the board."""

    def __init__(self):
        self.size = CANVAS_SIZE
        self.control_scale = 1.0
        self.sidebar_width = SIDEBAR_WIDTH
        self.canvas = pygame.Surface(self.size)
        self.manager = pygame_gui.UIManager(
            self.size, theme_path=Path(__file__).with_name("theme.json")
        )
        self.sidebar = UIScrollingContainer(
            pygame.Rect(0, 0, SIDEBAR_WIDTH, 600), self.manager,
            allow_scroll_x=False, should_grow_automatically=False, object_id="#sidebar",
        )
        self.widgets: dict[str, UIButton] = {}
        self.dropdowns: dict[str, Dropdown] = {}
        self.result_window = None
        self.result_buttons: dict[str, UIButton] = {}
        self.result_title = ""
        self.notice_text = ""
        self.notice_remaining_ms = 0.0
        self._notice_surface = None
        self._stage_options = []
        self._selections = {}
        self._mode = "BFS"
        self._playback = False
        self._next = False
        self._layout_key = None
        self.labels = {}
        for name, title in (("stage", "Stage"),
                            ("mode", "Control mode"), ("heuristic", "A* heuristic"),
                            ("speed", "Playback speed")):
            self.labels[name] = UILabel(pygame.Rect(0, 0, 260, 26), title,
                                       self.manager, container=self.sidebar)
        self.resize(self.size)

    @property
    def result_open(self) -> bool:
        return self.result_window is not None

    def show_result(self, *, won: bool, can_advance: bool) -> None:
        if self.result_open:
            return
        self.dismiss_menus()
        self.show_notice("")
        self.result_title = (
            "You win!" if can_advance else "All stages complete!"
        ) if won else "You lose!"
        scale = self.control_scale
        width, height = round(420 * scale), round(190 * scale)
        rect = pygame.Rect(0, 0, width, height)
        rect.center = (self.size[0] // 2, self.size[1] // 2)
        self.result_window = UIWindow(
            rect, self.manager, object_id="#result_dialog", draggable=False,
        )
        self.result_window.set_blocking(True)
        container = self.result_window.get_container()
        inner_width = container.get_size()[0]
        UILabel(pygame.Rect(0, round(20 * scale), inner_width, round(42 * scale)),
                self.result_title, self.manager, container=container)
        actions = [("restart", "Replay" if won else "Retry")]
        if won and can_advance:
            actions.insert(0, ("next", "Next Stage"))
        gap = round(12 * scale)
        button_width = (inner_width - gap * (len(actions) + 1)) // len(actions)
        self.result_buttons = {
            name: UIButton(
                pygame.Rect(gap + index * (button_width + gap), round(90 * scale),
                            button_width, round(40 * scale)),
                label, self.manager, container=container,
            )
            for index, (name, label) in enumerate(actions)
        }

    def clear_result(self) -> None:
        if self.result_window is not None:
            self.result_window.kill()
        self.result_window = None
        self.result_buttons = {}
        self.result_title = ""

    def bind_buttons(self, buttons: Mapping[str, Button]) -> None:
        self.widgets = {
            name: UIButton(
                pygame.Rect(0, 0, 120, 44), button.label,
                self.manager, container=self.sidebar, object_id=f"#{name}",
            )
            for name, button in buttons.items()
        }

    def _dropdown(self, name, options, selected):
        if name in self.dropdowns:
            self.dropdowns[name].kill()
        self.dropdowns[name] = Dropdown(
            options, selected, pygame.Rect(0, 0, 260, 40), self.manager,
            container=self.sidebar, object_id=f"#{name}", expansion_height_limit=round(360 * self.control_scale),
        )
        self._layout_key = None

    def configure(
        self, levels: Sequence[Level], active_index: int,
        mode: str, heuristic: str, speed: float,
    ) -> None:
        options = [(f"{i + 1:02d}  {level.name}", str(i)) for i, level in enumerate(levels)]
        if options != self._stage_options:
            self._stage_options = options
            self._dropdown("stage", options, options[active_index])
        if "mode" not in self.dropdowns:
            self._dropdown("mode", list(MODES), mode)
            self._dropdown(
                "heuristic", [(h.label, h.name) for h in HEURISTICS.values()],
                (HEURISTICS[heuristic].label, heuristic),
            )
            self._dropdown(
                "speed", [(f"{v:g}×", str(v)) for v in PLAYBACK_SPEEDS],
                (f"{speed:g}×", str(speed)),
            )
        self._select("stage", options[active_index])
        self._select("mode", (mode, mode))
        self._select("heuristic", (HEURISTICS[heuristic].label, heuristic))
        self._select("speed", (f"{speed:g}×", str(speed)))
        if mode != self._mode:
            self.dismiss_menus()
        self._mode = mode

    def _select(self, name, option):
        # Do not overwrite a native selection before its queued event is handled.
        if self._selections.get(name) != option:
            self.dropdowns[name].select(option)
            self._selections[name] = option

    @staticmethod
    def _visible(widget, visible):
        if bool(widget.visible) != visible:
            widget.show() if visible else widget.hide()

    def sync_buttons(self, buttons: Mapping[str, Button]) -> None:
        for name, button in buttons.items():
            widget = self.widgets[name]
            if widget.text != button.label:
                widget.set_text(button.label)
            self._visible(widget, button.visible)
            if bool(widget.is_enabled) != button.enabled:
                widget.enable() if button.enabled else widget.disable()
        self._playback = buttons["playback"].visible
        self._next = buttons["next"].visible
        self._layout_controls()

    def _layout_controls(self):
        key = (self.size, self._mode, self._playback, self._next,
               tuple(self.dropdowns))
        if key == self._layout_key:
            return
        self._layout_key = key
        scale = self.control_scale
        gap, row = round(8 * scale), round(36 * scale)
        width = self.sidebar.rect.width - round(28 * scale)
        y = gap

        def place(widget, height=row):
            nonlocal y
            widget.set_relative_position((gap, y))
            widget.set_dimensions((width, height))
            y += height + gap

        if "next" in self.widgets and self.widgets["next"].visible:
            place(self.widgets["next"])
        for name in ("stage", "mode", "heuristic", "speed"):
            visible = name in self.dropdowns and (name != "heuristic" or self._mode == "A*")
            visible = visible and (name != "speed" or self._mode != "Manual")
            self._visible(self.labels[name], visible)
            if name in self.dropdowns:
                self._visible(self.dropdowns[name], visible)
            if visible:
                place(self.labels[name], round(22 * scale))
                place(self.dropdowns[name])
        if "solve" in self.widgets and self.widgets["solve"].visible:
            place(self.widgets["solve"])
        transport = [self.widgets[name] for name in ("playback", "step", "restart")
                     if name in self.widgets and self.widgets[name].visible]
        if transport:
            button_width = (width - gap * (len(transport) - 1)) // len(transport)
            for index, widget in enumerate(transport):
                widget.set_relative_position((gap + index * (button_width + gap), y))
                widget.set_dimensions((button_width, row))
            y += row + gap
        # Keep dropdown options inside the container's clipping area even when
        # the compact controls use less height than the viewport.
        self.sidebar.scrollable_container.set_relative_position((0, 0))
        self.sidebar.set_scrollable_area_dimensions(
            (self.sidebar.rect.width - 20, max(y, self.sidebar.rect.height))
        )
        if self.sidebar.vert_scroll_bar is not None:
            self.sidebar.vert_scroll_bar.set_scroll_from_start_percentage(0)

    @property
    def menu_open(self) -> bool:
        return any(menu.is_open for menu in self.dropdowns.values())

    def dismiss_menus(self) -> None:
        for menu in self.dropdowns.values():
            menu.dismiss()

    def resize(self, size: tuple[int, int]) -> None:
        self.dismiss_menus()
        self.size = size
        self.control_scale = max(1.0, min(size[0] / CANVAS_SIZE[0], size[1] / CANVAS_SIZE[1]))
        scale = self.control_scale
        for menu in self.dropdowns.values():
            menu.expansion_height_limit = round(360 * scale)
        self.sidebar_width = round(SIDEBAR_WIDTH * scale)
        self.canvas = pygame.Surface(size)
        self.manager.set_window_resolution(size)
        font = {"name": "noto_sans", "size": str(round(15 * scale))}
        selectors = (
            "defaults", "button", "label",
            "drop_down_menu", "drop_down_menu.button", "drop_down_menu.@selected_option",
            "selection_list", "selection_list.button", "drop_down_menu.selection_list.button",
            "tool_tip.text_box",
        )
        updates = {selector: {"font": font.copy()} for selector in selectors}
        for selector in ("drop_down_menu.#expand_button", "vertical_scroll_bar.button",
                         "horizontal_scroll_bar.button"):
            updates[selector] = {"font": {"name": "fira_code_symbols",
                                          "size": str(round(15 * scale))}}
        updates["button"]["misc"] = {"text_horiz_alignment_padding": str(round(12 * scale))}
        updates["selection_list"]["misc"] = {"list_item_height": str(round(48 * scale))}
        updates["tool_tip.text_box"]["misc"] = {"padding": f"{round(8*scale)},{round(6*scale)}"}
        for label in self.labels.values():
            label.set_dimensions((round(280 * scale), round(34 * scale)))
        theme = self.manager.get_theme()
        theme.load_theme(updates)
        self.manager.rebuild_all_from_changed_theme_data(theme)
        margin = round(16 * scale)
        self.sidebar_width = round(310 * scale)
        self.panel_rect = pygame.Rect(margin, margin, self.sidebar_width, size[1] - margin * 2)
        self.board_rect = pygame.Rect(
            self.panel_rect.right + margin, margin,
            size[0] - self.panel_rect.right - margin * 2, size[1] - margin * 2,
        )
        self._background = pygame.Surface(size)
        self._background.fill("#101820")
        pygame.draw.rect(self._background, "#182331", self.panel_rect, border_radius=6)
        self.board_surface = pygame.Surface(self.board_rect.size, pygame.SRCALPHA)
        self.sidebar.set_relative_position(self.panel_rect.topleft)
        self.sidebar.set_dimensions(self.panel_rect.size)
        self._layout_key = None
        self._layout_controls()
        self._render_notice()
        if self.result_open:
            won = self.result_title != "You lose!"
            can_advance = "next" in self.result_buttons
            self.clear_result()
            self.show_result(won=won, can_advance=can_advance)

    def show_notice(self, text: str) -> None:
        """Show a small non-blocking message for one second, then fade it out."""
        self.notice_text = text
        self.notice_remaining_ms = NOTICE_MS if text else 0.0
        self._render_notice()

    @property
    def notice_alpha(self) -> int:
        return round(255 * min(1.0, self.notice_remaining_ms / NOTICE_FADE_MS))

    def _render_notice(self) -> None:
        self._notice_surface = None
        if not self.notice_text:
            return
        font = pygame.font.Font(None, round(24 * self.control_scale))
        text = font.render(self.notice_text, True, "#F5E9D3")
        padding = round(12 * self.control_scale)
        size = (text.get_width() + padding * 2, text.get_height() + padding * 2)
        self._notice_surface = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(self._notice_surface, "#29343E", self._notice_surface.get_rect(),
                         border_radius=6)
        self._notice_surface.blit(text, (padding, padding))

    def process_event(self, event: pygame.event.Event) -> bool:
        attributes = event.dict.copy()
        if event.type in (pygame.KEYDOWN, pygame.KEYUP):
            attributes.setdefault("mod", 0)
            attributes.setdefault("unicode", "")
        return self.manager.process_events(pygame.event.Event(event.type, attributes))

    def update(self, elapsed_ms: float):
        elapsed_ms = max(0, elapsed_ms)
        self.manager.update(elapsed_ms / 1000)
        if self.notice_remaining_ms:
            self.notice_remaining_ms = max(0, self.notice_remaining_ms - elapsed_ms)
            if not self.notice_remaining_ms:
                self.notice_text = ""
                self._notice_surface = None

    def draw(self, screen: pygame.Surface, *, board: Board):
        self.canvas.blit(self._background, (0, 0))
        board.draw(self.board_surface)
        self.canvas.blit(self.board_surface, self.board_rect)
        if self._notice_surface is not None:
            self._notice_surface.set_alpha(self.notice_alpha)
            rect = self._notice_surface.get_rect(
                midtop=(self.board_rect.centerx, self.board_rect.top + round(24 * self.control_scale))
            )
            self.canvas.blit(self._notice_surface, rect)
        self.manager.draw_ui(self.canvas)
        screen.blit(self.canvas, (0, 0))
        pygame.display.flip()
