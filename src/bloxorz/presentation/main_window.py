"""Desktop manual-play interface, with no search or algorithm dependencies."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bloxorz.application.game_session import GameSession, SessionStatus
from bloxorz.domain.models import Action, EventType, Level, Outcome, SplitBlock
from bloxorz.infrastructure.level_loader import LevelFormatError, builtin_levels, load_level
from bloxorz.presentation.board_widget import BoardWidget

STYLES = """
QWidget { color: #21374B; font-size: 14px; }
QWidget#gameArea { background: #172D42; }
QFrame#sidebar { background: #F2F6F8; }
QLabel#title { color: #F6F8FA; font-size: 34px; font-weight: 700; }
QLabel#subtitle, QLabel#keyHint { color: #A8BFCE; font-size: 13px; }
QLabel#mode { color: #B9E0DE; background: #25475A; padding: 7px 12px; border-radius: 4px; }
QLabel#stageTitle { color: #E4EDF3; font-size: 19px; font-weight: 600; }
QLabel#blockStatus { color: #A8BFCE; font-size: 13px; }
QLabel#counter { color: #F0C78C; font-size: 27px; font-weight: 600; }
QLabel#counterTitle { color: #A8BFCE; font-size: 12px; }
QLabel#sectionTitle { font-size: 21px; font-weight: 600; }
QLabel#sectionLabel { font-size: 14px; font-weight: 600; }
QLabel#description { color: #51697A; font-size: 13px; line-height: 1.4; }
QLabel#smallHint { color: #627B8B; font-size: 12px; }
QLabel#legend { color: #B9CEDA; font-size: 12px; }
QComboBox { background: white; border: 1px solid #B7C9D3; border-radius: 5px; padding: 9px; }
QComboBox:focus { border: 2px solid #237A84; }
QComboBox QAbstractItemView {
    background: white; selection-background-color: #DAEEEE; selection-color: #21374B;
}
QPushButton {
    background: #E0E9EE; border: 1px solid #B7C9D3; border-radius: 5px;
    padding: 9px 12px; font-weight: 500;
}
QPushButton:hover { background: #D0E0E8; border-color: #7E9BAB; }
QPushButton:pressed { background: #BBD1DD; }
QPushButton:focus { border: 2px solid #237A84; }
QPushButton:disabled { color: #95A6B1; background: #E8EEF1; border-color: #D4E0E6; }
QPushButton#primary { color: white; background: #236D77; border-color: #236D77; }
QPushButton#primary:hover { background: #195B65; }
QPushButton#primary:focus { border: 2px solid #152F41; }
QPushButton#openLevel {
    background: transparent; border: none; color: #326B7C; font-size: 12px; padding: 4px;
}
QPushButton#openLevel:focus { border: 2px solid #237A84; }
QPushButton#direction { font-size: 20px; padding: 4px; min-height: 27px; }
QFrame#divider { background: #CEDDE5; max-height: 1px; }
QFrame#statusCard { background: #E0EBF0; border-radius: 6px; }
QFrame#statusCard[outcome="won"] { background: #D5EBE2; }
QFrame#statusCard[outcome="lost"] { background: #F3DED5; }
QLabel#statusHeading { font-size: 17px; font-weight: 600; background: transparent; }
QLabel#statusBody { color: #4C6577; font-size: 13px; background: transparent; }
"""


class MainWindow(QMainWindow):
    """Connect controls to the game session and display its immutable snapshots."""

    def __init__(self, levels: Sequence[Level] | None = None):
        super().__init__()
        self.levels = list(builtin_levels() if levels is None else levels)
        if not self.levels:
            raise ValueError("At least one level is required")
        self.session = GameSession(self.levels[0])
        self.setWindowTitle("Bloxorz — Manual play")
        self.resize(1160, 800)
        self.setMinimumSize(900, 740)
        self.setStyleSheet(STYLES)
        self._build_layout()
        self._refresh()
        self.board.setFocus()

    def _build_layout(self) -> None:
        """Keep the board central and group all controls in a single sidebar."""
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)
        layout.addWidget(self._build_game_area(), 1)
        layout.addWidget(self._build_sidebar())

    def _build_game_area(self) -> QWidget:
        area = QWidget()
        area.setObjectName("gameArea")
        layout = QVBoxLayout(area)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self._label("Bloxorz", "title"))
        titles.addWidget(self._label("A block-rolling puzzle", "subtitle"))
        header.addLayout(titles)
        header.addStretch()
        header.addWidget(self._label("Manual play", "mode"), alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addLayout(self._build_board_header())
        self.board = BoardWidget()
        self.board.action_requested.connect(self.play)
        self.board.restart_requested.connect(self.restart)
        self.board.animation_finished.connect(self._refresh)
        layout.addWidget(self.board, 1)
        layout.addLayout(self._build_legend())
        hint = self._label(
            "Arrows / WASD to roll     Space to switch cubes     R to restart", "keyHint"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return area

    def _build_board_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(6)
        self.stage_title = self._label("", "stageTitle")
        self.stage_title.setWordWrap(True)
        self.block_status = self._label("", "blockStatus")
        titles.addWidget(self.stage_title)
        titles.addWidget(self.block_status)
        header.addLayout(titles, 1)
        self.roll_value = self._add_counter(header, "Rolls")
        self.swap_value = self._add_counter(header, "Swaps")
        return header

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(300)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(24, 30, 24, 24)
        layout.setSpacing(10)
        layout.addWidget(self._label("Your next move", "sectionTitle"))
        layout.addSpacing(6)
        layout.addWidget(self._label("Stage", "sectionLabel"))
        self.level_selector = QComboBox()
        self.level_selector.setAccessibleName("Choose a stage")
        for index, level in enumerate(self.levels, 1):
            self.level_selector.addItem(f"{index:02d}   {level.name}")
        layout.addWidget(self.level_selector)
        self.new_game_button = self._button("New game", self.start_selected_level, "primary")
        layout.addWidget(self.new_game_button)
        layout.addWidget(self._button("Open level file…", self._open_level, "openLevel"))
        self.description = self._label("", "description")
        self.description.setWordWrap(True)
        self.description.setMinimumHeight(64)
        layout.addWidget(self.description)
        divider = QFrame()
        divider.setObjectName("divider")
        layout.addWidget(divider)
        layout.addWidget(self._label("Move the block", "sectionLabel"))
        layout.addLayout(self._build_direction_controls())
        self.swap_button = self._button(
            "Switch cube   ·   Space", lambda: self.play(Action.SWAP_ACTIVE_CUBE)
        )
        layout.addWidget(self.swap_button)
        layout.addWidget(self._label("The white outline marks the active cube.", "smallHint"))
        layout.addStretch(1)
        layout.addWidget(self._build_status_card())
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.restart_button = self._button("Restart   ·   R", self.restart)
        footer.addWidget(self.restart_button, 1)
        self.next_stage_button = self._button("Next stage", self.next_stage, "primary")
        footer.addWidget(self.next_stage_button, 1)
        layout.addLayout(footer)
        goal_hint = self._label("Reach the goal standing upright.", "smallHint")
        goal_hint.setWordWrap(True)
        layout.addWidget(goal_hint)
        return sidebar

    def _build_direction_controls(self) -> QGridLayout:
        controls = QGridLayout()
        controls.setSpacing(6)
        self.direction_buttons = {}
        for action, symbol, row, col in (
            (Action.UP, "↑", 0, 1),
            (Action.LEFT, "←", 1, 0),
            (Action.DOWN, "↓", 1, 1),
            (Action.RIGHT, "→", 1, 2),
        ):
            button = self._button(
                symbol, lambda checked=False, direction=action: self.play(direction), "direction"
            )
            button.setAccessibleName(f"Move {action.value}")
            button.setToolTip(f"Move {action.value}")
            self.direction_buttons[action.value] = button
            controls.addWidget(button, row, col)
        return controls

    def _build_status_card(self) -> QFrame:
        self.status_card = QFrame()
        self.status_card.setObjectName("statusCard")
        layout = QVBoxLayout(self.status_card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        self.status_heading = self._label("", "statusHeading")
        self.status_body = self._label("", "statusBody")
        self.status_body.setWordWrap(True)
        self.status_body.setMinimumHeight(48)
        layout.addWidget(self.status_heading)
        layout.addWidget(self.status_body)
        return self.status_card

    def _build_legend(self) -> QGridLayout:
        legend = QGridLayout()
        legend.setHorizontalSpacing(14)
        legend.setVerticalSpacing(8)
        for index, text in enumerate(
            (
                "■  Floor",
                "G  Goal",
                "▧  Fragile",
                "≡  Bridge",
                "○  Soft",
                "×  Heavy",
                "( )  Split",
                "◌  Start",
            )
        ):
            legend.addWidget(self._label(text, "legend"), index // 4, index % 4)
        return legend

    def play(self, action: Action) -> None:
        """Commit one action and finish its visual timeline before accepting more."""
        if self.board.is_animating:
            return
        previous = self.session.state
        result = self.session.apply_action(action)
        if (
            result
            and result.outcome is not Outcome.INVALID
            and action is not Action.SWAP_ACTIVE_CUBE
        ):
            self.board.animate_move(self.session.level, previous, action, result)
            self._refresh(update_board=False)
        else:
            self._refresh()
        self.board.setFocus(Qt.FocusReason.OtherFocusReason)

    def restart(self) -> None:
        """Restore the active stage without changing the selector's pending choice."""
        self.session.restart()
        self._refresh()
        self.board.setFocus(Qt.FocusReason.OtherFocusReason)

    def start_selected_level(self) -> None:
        """Start the selected stage only after New game is pressed."""
        self.session = GameSession(self.levels[self.level_selector.currentIndex()])
        self._refresh()
        self.board.setFocus(Qt.FocusReason.OtherFocusReason)

    def next_stage(self) -> None:
        """Advance from a completed stage, retaining deterministic stage order."""
        index = self.levels.index(self.session.level)
        if index + 1 < len(self.levels):
            self.level_selector.setCurrentIndex(index + 1)
            self.start_selected_level()

    def _open_level(self) -> None:
        """Load a user-selected stage and preserve the session if parsing fails."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Bloxorz level", "", "JSON levels (*.json)"
        )
        if not path:
            return
        try:
            level = load_level(path)
        except LevelFormatError as exc:
            QMessageBox.warning(self, "Cannot load this level", str(exc))
            return
        self.levels.append(level)
        self.level_selector.addItem(f"{len(self.levels):02d}   {level.name}")
        self.level_selector.setCurrentIndex(len(self.levels) - 1)
        self.start_selected_level()

    def _refresh(self, *, update_board: bool = True) -> None:
        """Update labels and enabled controls from the session's outcome."""
        session = self.session
        if update_board:
            self.board.display(
                session.level,
                session.state,
                lost=session.status is SessionStatus.LOST,
                won=session.status is SessionStatus.WON,
            )
        index = self.levels.index(session.level)
        self.stage_title.setText(f"{index + 1:02d} / {session.level.name}")
        self.description.setText(session.level.description)
        self.roll_value.setText(str(session.roll_count))
        self.swap_value.setText(str(session.swap_count))
        block = session.state.block
        split = isinstance(block, SplitBlock)
        self.block_status.setText(
            "Moving…"
            if self.board.is_animating
            else (
                f"Cube {'A' if block.active_cube == 0 else 'B'} active"
                if split
                else block.orientation.value.replace("_", " ").capitalize()
            )
        )
        playing = session.status is SessionStatus.PLAYING and not self.board.is_animating
        for button in self.direction_buttons.values():
            button.setEnabled(playing)
        self.swap_button.setEnabled(playing and split)
        self.next_stage_button.setVisible(
            session.status is SessionStatus.WON
            and not self.board.is_animating
            and index + 1 < len(self.levels)
        )
        heading, body = self._status_text()
        self.status_heading.setText(heading)
        self.status_body.setText(body)
        self.status_card.setProperty(
            "outcome",
            SessionStatus.PLAYING.value if self.board.is_animating else session.status.value,
        )
        self.status_card.style().unpolish(self.status_card)
        self.status_card.style().polish(self.status_card)

    def _status_text(self) -> tuple[str, str]:
        """Explain outcomes with a concrete next action and no blocking dialogs."""
        if self.board.is_animating:
            return "In motion", "Wait for the block to settle. You can restart at any time."
        if self.session.status is SessionStatus.WON:
            return (
                "Stage complete",
                f"Home in {self.session.roll_count} rolls. "
                "Choose another stage or restart to play again.",
            )
        result = self.session.last_result
        if self.session.status is SessionStatus.LOST:
            reasons = {
                "out_of_bounds": "The block rolled off the board.",
                "unsupported": "Part of the block has no floor beneath it.",
                "fragile": "The upright block broke a fragile tile.",
            }
            return "Try again", reasons.get(
                result.reason, "The block fell."
            ) + " Press R to restart."
        if result and result.outcome is Outcome.INVALID:
            return (
                "Keep going",
                "That action is unavailable. Move the block or switch cubes after splitting.",
            )
        if result:
            for event in reversed(result.events):
                messages = {
                    EventType.BLOCK_SPLIT: "Two cubes now. Press Space to switch control.",
                    EventType.BLOCK_MERGED: "Back together. Reach the goal standing upright.",
                    EventType.BRIDGE_OPENED: "Bridge opened. Turquoise tiles are safe to cross.",
                    EventType.BRIDGE_CLOSED: "Bridge closed. Avoid the dashed turquoise cells.",
                }
                if event.kind in messages:
                    return "Keep going", messages[event.kind]
        return (
            "Ready to roll",
            "Use the arrow keys or the controls above. Keep the whole block on the board.",
        )

    def closeEvent(self, event) -> None:
        """Stop the owned animation clock before this window is closed."""
        self.board.cancel_animation()
        super().closeEvent(event)

    @staticmethod
    def _label(text: str, name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    @staticmethod
    def _button(text: str, callback, name: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def _add_counter(self, layout: QHBoxLayout, title: str) -> QLabel:
        column = QVBoxLayout()
        column.setSpacing(0)
        value = self._label("0", "counter")
        column.addWidget(value, alignment=Qt.AlignmentFlag.AlignRight)
        column.addWidget(self._label(title, "counterTitle"))
        layout.addSpacing(20)
        layout.addLayout(column)
        return value


def main(argv: list[str] | None = None) -> int:
    """Launch the application, optionally opening an external JSON stage."""
    parser = argparse.ArgumentParser(description="Play Bloxorz with all advanced tile mechanics.")
    parser.add_argument("--level", type=Path, help="Open an additional JSON stage")
    args = parser.parse_args(argv)
    levels = list(builtin_levels())
    if args.level:
        try:
            levels.insert(0, load_level(args.level))
        except LevelFormatError as exc:
            parser.error(str(exc))
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Bloxorz")
    window = MainWindow(levels)
    window.show()
    return app.exec()
