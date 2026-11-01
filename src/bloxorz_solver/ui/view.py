"""Native solver controls alongside the shared game background."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pygame
import pygame_gui
from pygame_gui.elements import (
    UIButton,
    UIDropDownMenu,
    UILabel,
    UIPanel,
    UIScrollingContainer,
    UIWindow,
)

from bloxorz_solver.game.state import Level
from bloxorz_solver.solvers.base import SearchResult
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
    "playback": "⏯",
    "cancel": "Cancel", "prev_stage": "‹", "next_stage": "›",
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
        self._preloaded_scales = set()
        self.manager = pygame_gui.UIManager(
            self.size, theme_path=Path(__file__).with_name("theme.json")
        )
        self.manager.add_font_paths("transport_symbols", str(
            Path(__file__).with_name("fonts") / "NotoSansSymbols2-Regular.ttf"))
        self._preload_fonts(1.0)
        self.sidebar = UIScrollingContainer(
            pygame.Rect(0, 0, SIDEBAR_WIDTH, 600), self.manager,
            allow_scroll_x=False, should_grow_automatically=False, object_id="#sidebar",
        )
        self.cards = {
            name: UIPanel(pygame.Rect(0, 0, 280, 100), starting_height=0,
                          manager=self.manager, container=self.sidebar, object_id="#card")
            for name in ("stage", "controls", "metrics")
        }
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
        self._notice_fonts = {}
        self.status = UILabel(pygame.Rect(0, 0, 260, 28), "Idle", self.manager,
                              container=self.sidebar, object_id="#status")
        self.metric_labels = {
            name: UILabel(pygame.Rect(0, 0, 260, 26), text,
                          self.manager, container=self.sidebar,
                          object_id="#heading" if name == "title" else "#metric_value")
            for name, text in (
                ("title", "Search metrics"),
                ("search_time", "Search time: —"),
                ("peak_memory", "Peak memory: —"),
                ("expanded_nodes", "Expanded nodes: —"),
                ("solution_length", "Solution length: —"),
            )
        }
        for name, title in (("stage", "Stage"),
                            ("mode", "Algorithm"), ("heuristic", "A* heuristic")):
            self.labels[name] = UILabel(pygame.Rect(0, 0, 260, 26), title,
                                       self.manager, container=self.sidebar,
                                       object_id="#heading" if name in ("stage", "mode") else "#label")
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
        width, height = round(600 * scale), round(230 * scale)
        rect = pygame.Rect(0, 0, width, height)
        rect.center = (self.size[0] // 2, self.size[1] // 2)
        self.result_window = UIWindow(
            rect, self.manager, object_id="#result_dialog", draggable=False,
        )
        self.result_window.set_blocking(True)
        container = self.result_window.get_container()
        inner_width = container.get_size()[0]
        padding = round(24 * scale)
        UILabel(pygame.Rect(padding, round(20 * scale),
                            inner_width - 2 * padding, round(90 * scale)),
                self.result_title, self.manager, container=container,
                object_id="#result_title_win" if won else "#result_title_lose")
        actions = [("restart", "Replay" if won else "Retry")]
        if won and can_advance:
            actions.insert(0, ("next", "Next Stage"))
        gap = round(12 * scale)
        button_width = (inner_width - gap * (len(actions) + 1)) // len(actions)
        self.result_buttons = {
            name: UIButton(
                pygame.Rect(gap + index * (button_width + gap), round(140 * scale),
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
        tips = {"playback": "Play / pause", "cancel": "Cancel search",
                "prev_stage": "Previous stage", "next_stage": "Next stage"}
        for name, tip in tips.items():
            self.widgets[name].set_tooltip(tip)

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
        mode: str, heuristic: str,
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
        self._select("stage", options[active_index])
        self._select("mode", (mode, mode))
        self._select("heuristic", (HEURISTICS[heuristic].label, heuristic))
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

    def sync_metrics(self, result: SearchResult | None) -> None:
        """Display the latest search without rebuilding widgets each frame."""
        values = dict.fromkeys(
            ("search_time", "peak_memory", "expanded_nodes", "solution_length"), "—"
        )
        if result is not None:
            seconds = result.search_time
            values["search_time"] = f"{seconds * 1000:,.2f} ms"
            memory = result.peak_memory
            values["peak_memory"] = f"{memory / 1_000_000:,.3f} MB"
            values["expanded_nodes"] = f"{result.expanded_nodes:,}"
            if result.is_found:
                values["solution_length"] = f"{result.solution_length:,}"
        for name, value in values.items():
            title = name.replace("_", " ").capitalize()
            text = f"{title}: {value}"
            if self.metric_labels[name].text != text:
                self.metric_labels[name].set_text(text)

    def _layout_controls(self):
        key = (self.size, self._mode, self._playback, self._next,
               tuple(self.dropdowns), tuple((name, bool(w.visible))
                                           for name, w in self.widgets.items()))
        if key == self._layout_key:
            return
        self._layout_key = key
        scale = self.control_scale
        gap, row, padding, separation = (round(v * scale) for v in (6, 36, 16, 20))
        outer = round(6 * scale)
        card_width = self.sidebar.rect.width - 20 - 2 * outer
        x = outer + padding
        width = card_width - 2 * padding
        y = outer

        def size_widget(widget, dimensions):
            changed = widget.relative_rect.size != dimensions
            widget.set_dimensions(dimensions)
            if changed and isinstance(widget, UIButton):
                # pygame_gui's rapid resize can retain old surfaces for inactive
                # states. Rebuild so disabling a button uses its current size.
                widget.rebuild()

        def place(widget, height=row):
            nonlocal y
            widget.set_relative_position((x, y))
            size_widget(widget, (width, height))
            y += height + gap

        def begin(name):
            nonlocal y
            self.cards[name].show()
            start = y
            y += padding
            return start

        def finish(name, start):
            nonlocal y
            y += padding - gap
            card = self.cards[name]
            card.set_relative_position((outer, start))
            card.set_dimensions((card_width, y - start))
            y += separation

        def selector(name, visible, heading=True):
            self._visible(self.labels[name], visible)
            if name in self.dropdowns:
                self._visible(self.dropdowns[name], visible)
                if visible:
                    if heading:
                        place(self.labels[name], round(24 * scale))
                    place(self.dropdowns[name])

        start = begin("stage")
        selector("stage", "stage" in self.dropdowns)
        if "stage" in self.dropdowns and "prev_stage" in self.widgets:
            stage = self.dropdowns["stage"]
            arrow = round(28 * scale)
            stage.set_relative_position((x + arrow + gap, stage.relative_rect.y))
            stage.set_dimensions((width - 2*(arrow+gap), row))
            for name, left in (("prev_stage", x), ("next_stage", x+width-arrow)):
                self.widgets[name].set_relative_position((left, stage.relative_rect.y))
                size_widget(self.widgets[name], (arrow, row))
        if "next" in self.widgets and self.widgets["next"].visible:
            place(self.widgets["next"])
        finish("stage", start)

        start = begin("controls")
        selector("mode", "mode" in self.dropdowns)
        selector("heuristic", self._mode == "A*")
        for name in ("solve", "cancel"):
            if name in self.widgets and self.widgets[name].visible:
                place(self.widgets[name])
        if "restart" in self.widgets:
            place(self.widgets["restart"])
        place(self.status, round(28 * scale))

        solver = self._mode != "Manual"
        if solver:
            transport = [self.widgets[name] for name in ("playback",)
                         if name in self.widgets and self.widgets[name].visible]
            if transport:
                button_width = (width - gap * (len(transport) - 1)) // len(transport)
                for index, widget in enumerate(transport):
                    widget.set_relative_position((x + index * (button_width + gap), y))
                    size_widget(widget, (button_width, row))
                y += row + gap
        finish("controls", start)

        self._visible(self.cards["metrics"], solver)
        for label in self.metric_labels.values():
            self._visible(label, solver)
        if solver:
            start = begin("metrics")
            for label in self.metric_labels.values():
                place(label, round(26 * scale))
            finish("metrics", start)

        self.sidebar.scrollable_container.set_relative_position((0, 0))
        self.sidebar.set_scrollable_area_dimensions(
            (self.sidebar.rect.width - 20, max(y, self.sidebar.rect.height))
        )
        # Preserve scroll position across search/status changes. Resize starts at the top.

    @property
    def menu_open(self) -> bool:
        return any(menu.is_open for menu in self.dropdowns.values())

    def dismiss_menus(self) -> None:
        for menu in self.dropdowns.values():
            menu.dismiss()

    def _preload_fonts(self, scale):
        if scale in self._preloaded_scales:
            return
        fonts = self.manager.get_theme().get_font_dictionary()
        requests = []
        for name, size, style in (("noto_sans", 15, "regular"),
                                  ("noto_sans", 15, "bold"),
                                  ("noto_sans", 48, "bold"),
                                  ("noto_sans", 18, "regular"),
                                  ("fira_code_symbols", 15, "regular"),
                                  ("transport_symbols", 18, "regular")):
            size = round(size * scale)
            font_id = fonts.create_font_id(size, name, style == "bold", False, True)
            if font_id not in fonts.loaded_fonts:
                requests.append({"name": name, "point_size": size, "style": style})
        self.manager.preload_fonts(requests)
        self._preloaded_scales.add(scale)

    def resize(self, size: tuple[int, int]) -> None:
        self.dismiss_menus()
        self.size = size
        self.control_scale = max(1.0, min(size[0] / CANVAS_SIZE[0], size[1] / CANVAS_SIZE[1]))
        scale = self.control_scale
        notice_size = round(24 * scale)
        if notice_size not in self._notice_fonts:
            self._notice_fonts[notice_size] = pygame.font.Font(None, notice_size)
        for menu in self.dropdowns.values():
            menu.expansion_height_limit = round(360 * scale)
        self.sidebar_width = round(SIDEBAR_WIDTH * scale)
        self.canvas = pygame.Surface(size)
        self.manager.set_window_resolution(size)
        self._preload_fonts(scale)
        font = {"name": "noto_sans", "size": str(round(15 * scale))}
        selectors = (
            "defaults", "button", "label",
            "drop_down_menu", "drop_down_menu.button", "drop_down_menu.@selected_option",
            "selection_list", "selection_list.button", "drop_down_menu.selection_list.button",
            "tool_tip.text_box",
        )
        updates = {selector: {"font": font.copy()} for selector in selectors}
        for outcome in ("win", "lose"):
            updates[f"#result_title_{outcome}"] = {
                "font": {**font, "size": str(round(48 * scale)), "bold": "1"},
            }
        for name in ("playback", "prev_stage", "next_stage"):
            updates[f"#{name}"] = {"font": {"name": ("transport_symbols" if name in
                                                       ("playback",)
                                                       else "noto_sans"),
                                             "size": str(round(18 * scale))},
                                   "misc": {"text_horiz_alignment_padding": "0"}}
        for selector in ("drop_down_menu.#expand_button", "vertical_scroll_bar.button",
                         "horizontal_scroll_bar.button"):
            updates[selector] = {"font": {"name": "fira_code_symbols",
                                          "size": str(round(15 * scale))}}
        for selector, weight in (("#metric_value", "0"), ("#heading", "1")):
            updates[selector] = {"font": {**font, "bold": weight}}
        updates["button"]["misc"] = {"text_horiz_alignment_padding": str(round(12 * scale))}
        updates["selection_list"]["misc"] = {"list_item_height": str(round(48 * scale))}
        updates["tool_tip.text_box"]["misc"] = {"padding": f"{round(8*scale)},{round(6*scale)}"}
        for label in (*self.labels.values(), *self.metric_labels.values(), self.status):
            label.set_dimensions((round(280 * scale), round(34 * scale)))
        theme = self.manager.get_theme()
        theme.load_theme(updates)
        self.manager.rebuild_all_from_changed_theme_data(theme)
        margin = round(16 * scale)
        self.sidebar_width = round(340 * scale)
        self.panel_rect = pygame.Rect(margin, margin, self.sidebar_width, size[1] - margin * 2)
        self.board_rect = pygame.Rect(
            self.panel_rect.right + margin, margin,
            size[0] - self.panel_rect.right - margin * 2, size[1] - margin * 2,
        )
        self._background = pygame.Surface(size)
        self._background.fill("#F4F9FF")
        pygame.draw.rect(self._background, "#FFFFFF", self.panel_rect, border_radius=12)
        pygame.draw.rect(self._background, "#D6E6FF", self.panel_rect, width=1,
                         border_radius=12)
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
        font = self._notice_fonts[round(24 * self.control_scale)]
        text = font.render(self.notice_text, True, "#1F2A44")
        padding = round(12 * self.control_scale)
        size = (text.get_width() + padding * 2, text.get_height() + padding * 2)
        self._notice_surface = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(self._notice_surface, "#FFFFFF", self._notice_surface.get_rect(),
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

    def draw(self, screen: pygame.Surface, *, board: Board, bad_apple=None):
        is_bad_apple = bool(bad_apple and bad_apple.state.active)
        if is_bad_apple:
            # Fullscreen black background for Bad Apple theater mode
            self.canvas.fill((10, 10, 14))
            board.draw(self.board_surface, bad_apple=bad_apple)
            # Center the board surface across the full canvas
            board_dest = self.board_surface.get_rect(center=self.canvas.get_rect().center)
            self.canvas.blit(self.board_surface, board_dest)
            screen.blit(self.canvas, (0, 0))
            pygame.display.flip()
            return

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
