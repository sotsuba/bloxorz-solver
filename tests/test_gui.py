"""Headless integration checks for the real Qt interface."""

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from bloxorz.application.game_session import SessionStatus
from bloxorz.domain.engine import initial_state
from bloxorz.domain.models import (
    Action,
    Bridge,
    BridgeEffect,
    EffectMode,
    GameState,
    NormalBlock,
    Orientation,
    Position,
    SplitBlock,
    Switch,
    SwitchKind,
)
from bloxorz.presentation.board_widget import BRIDGE_MS, FALL_MS, ROLL_MS
from bloxorz.presentation.main_window import MainWindow
from bloxorz.presentation.motion import BLOCK_INSET, block_meshes


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def finish_motion(window):
    """Seek Qt's real animation clock to its endpoint without sleeping."""
    if window.board.is_animating:
        window.board.animation.setCurrentTime(window.board.animation.duration())


def press(window, key):
    """Make one player move and finish its visual effects deterministically."""
    QTest.keyClick(window.board, key)
    finish_motion(window)


def test_window_renders_all_bundled_levels(window, app):
    for index in range(window.level_selector.count()):
        window.level_selector.setCurrentIndex(index)
        QTest.mouseClick(window.new_game_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert window.session.level == window.levels[index]
        assert window.session.action_count == 0
        pixmap = window.grab()
        assert not pixmap.isNull()
        assert pixmap.width() >= 900


def test_keyboard_wins_and_restart_restores_controls(window):
    for _ in range(4):
        press(window, Qt.Key.Key_Right)
    assert window.session.status is SessionStatus.WON
    assert "Stage complete" in window.status_heading.text()
    assert all(not button.isEnabled() for button in window.direction_buttons.values())
    QTest.keyClick(window.board, Qt.Key.Key_R)
    assert window.session.status is SessionStatus.PLAYING
    assert window.session.roll_count == 0
    assert all(button.isEnabled() for button in window.direction_buttons.values())


def test_falling_shows_loss_and_button_restarts(window):
    press(window, Qt.Key.Key_Up)
    assert window.session.status is SessionStatus.LOST
    assert "Try again" in window.status_heading.text()
    QTest.mouseClick(window.restart_button, Qt.MouseButton.LeftButton)
    assert window.session.status is SessionStatus.PLAYING
    assert window.session.action_count == 0


def test_clicked_controls_return_keyboard_focus_to_board(window, app):
    QTest.mouseClick(window.direction_buttons["right"], Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.board.hasFocus()
    finish_motion(window)
    press(window, Qt.Key.Key_Right)
    assert window.session.roll_count == 2


def test_split_can_be_swapped_rejoined_and_completed(window, app, stage_routes):
    window.level_selector.setCurrentIndex(5)
    QTest.mouseClick(window.new_game_button, Qt.MouseButton.LeftButton)
    route = stage_routes["06_bridge_builders"]
    before_swap, after_swap = route.split("X")
    keys = {"U": Qt.Key.Key_Up, "D": Qt.Key.Key_Down, "L": Qt.Key.Key_Left, "R": Qt.Key.Key_Right}
    for letter in before_swap:
        press(window, keys[letter])
    assert isinstance(window.session.state.block, SplitBlock)
    assert window.swap_button.isEnabled()
    app.processEvents()
    assert not window.grab().isNull()
    QTest.mouseClick(window.swap_button, Qt.MouseButton.LeftButton)
    assert window.session.state.block.active_cube == 1
    for letter in after_swap:
        press(window, keys[letter])
    assert isinstance(window.session.state.block, NormalBlock)
    assert not window.swap_button.isEnabled()
    assert window.session.status is SessionStatus.WON
    assert window.session.swap_count == 1


def test_next_stage_starts_following_level(window):
    for _ in range(4):
        press(window, Qt.Key.Key_Right)
    QTest.mouseClick(window.next_stage_button, Qt.MouseButton.LeftButton)
    assert window.session.level.id == "02_light_touch"
    assert window.session.status is SessionStatus.PLAYING


def test_final_stage_completes_both_split_cycles_and_ends_campaign(window, app, stage_routes):
    window.level_selector.setCurrentIndex(9)
    window.start_selected_level()
    window.resize(900, 740)
    app.processEvents()
    label = window.description
    needed = (
        label.fontMetrics()
        .boundingRect(QRect(0, 0, label.width(), 1000), Qt.TextFlag.TextWordWrap, label.text())
        .height()
    )
    assert label.height() >= needed
    keys = {
        "U": Qt.Key.Key_Up,
        "D": Qt.Key.Key_Down,
        "L": Qt.Key.Key_Left,
        "R": Qt.Key.Key_Right,
        "X": Qt.Key.Key_Space,
    }
    for letter in stage_routes["10_the_long_way_home"]:
        press(window, keys[letter])
    assert window.session.status is SessionStatus.WON
    assert window.session.swap_count == 2
    assert not window.next_stage_button.isVisible()
    assert not window.board.is_animating
    assert "Stage complete" in window.status_heading.text()


def test_win_message_fits_at_minimum_window_size(window, app):
    window.resize(900, 740)
    for _ in range(4):
        press(window, Qt.Key.Key_Right)
    app.processEvents()
    label = window.status_body
    needed = (
        label.fontMetrics()
        .boundingRect(QRect(0, 0, label.width(), 1000), Qt.TextFlag.TextWordWrap, label.text())
        .height()
    )
    assert label.height() >= needed
    assert window.status_card.rect().contains(label.geometry())


def test_motion_ignores_overlapping_input_and_finishes_once(window):
    finished = QSignalSpy(window.board.animation_finished)
    QTest.keyClick(window.board, Qt.Key.Key_Right)
    expected = window.session.state
    assert window.board.is_animating
    assert all(not button.isEnabled() for button in window.direction_buttons.values())
    assert "In motion" in window.status_heading.text()
    QTest.keyClick(window.board, Qt.Key.Key_Right)
    QTest.keyClick(window.board, Qt.Key.Key_Space)
    assert window.session.roll_count == 1
    assert window.session.state == expected
    assert finished.count() == 0
    finish_motion(window)
    assert finished.count() == 1
    assert not window.board.is_animating
    assert all(button.isEnabled() for button in window.direction_buttons.values())


def test_roll_has_visible_intermediate_frames_without_mutating_state(window, app):
    QTest.keyClick(window.board, Qt.Key.Key_Right)
    state = window.session.state
    start = window.board.grab().toImage()
    window.board.animation.setCurrentTime(ROLL_MS // 2)
    app.processEvents()
    middle = window.board.grab().toImage()
    assert middle != start
    assert window.session.state == state
    assert window.board.phase == "roll"
    finish_motion(window)
    assert window.board.state == state


@pytest.mark.parametrize("falling", [False, True])
def test_restart_cancels_motion_without_stale_completion(window, falling):
    finished = QSignalSpy(window.board.animation_finished)
    QTest.keyClick(window.board, Qt.Key.Key_Up if falling else Qt.Key.Key_Right)
    if falling:
        window.board.animation.setCurrentTime(ROLL_MS + FALL_MS // 2)
    QTest.keyClick(window.board, Qt.Key.Key_R)
    assert not window.board.is_animating
    assert window.board.state == initial_state(window.session.level)
    assert window.session.status is SessionStatus.PLAYING
    assert window.session.action_count == 0
    assert not window.board._block_hidden
    QTest.qWait(30)
    assert finished.count() == 0
    assert window.session.action_count == 0


def test_changing_stage_cancels_pending_motion(window):
    QTest.keyClick(window.board, Qt.Key.Key_Right)
    window.level_selector.setCurrentIndex(5)
    QTest.mouseClick(window.new_game_button, Qt.MouseButton.LeftButton)
    assert not window.board.is_animating
    assert window.board.level.id == "06_bridge_builders"
    assert window.board.state == initial_state(window.session.level)
    assert window.session.action_count == 0


def test_bridges_open_and_close_after_landing(window, app):
    window.level_selector.setCurrentIndex(2)
    window.start_selected_level()
    press(window, Qt.Key.Key_Up)
    press(window, Qt.Key.Key_Right)
    for before, after in ((0.0, 1.0), (1.0, 0.0)):
        QTest.keyClick(window.board, Qt.Key.Key_Right)
        assert window.board._bridge_openness("crossing") == before
        window.board.animation.setCurrentTime(ROLL_MS + BRIDGE_MS // 2)
        assert window.board.phase == "bridge"
        assert window.board._bridge_openness("crossing") == pytest.approx(0.5)
        app.processEvents()
        assert not window.board.grab().isNull()
        finish_motion(window)
        assert window.board._bridge_openness("crossing") == after
        if after == 1:
            press(window, Qt.Key.Key_Left)


def test_restart_during_bridge_motion_restores_initial_mask(window):
    window.level_selector.setCurrentIndex(2)
    window.start_selected_level()
    press(window, Qt.Key.Key_Up)
    press(window, Qt.Key.Key_Right)
    QTest.keyClick(window.board, Qt.Key.Key_Right)
    window.board.animation.setCurrentTime(ROLL_MS + BRIDGE_MS // 2)
    window.restart()
    assert window.board._bridge_openness("crossing") == 0
    assert window.session.state.bridge_mask == 0
    assert not window.board.is_animating


def test_goal_sinks_before_showing_completion_and_stays_hidden(window, app):
    for _ in range(3):
        press(window, Qt.Key.Key_Right)
    QTest.keyClick(window.board, Qt.Key.Key_Right)
    assert window.session.status is SessionStatus.WON
    assert not window.next_stage_button.isVisible()
    assert not window.board._block_hidden
    window.board.animation.setCurrentTime(ROLL_MS + FALL_MS // 2)
    assert window.board.phase == "fall"
    vertices = window.board._frame_meshes()[0][0].vertices
    assert min(point[2] for point in vertices) < 0
    assert max(point[2] for point in vertices) > BLOCK_INSET
    app.processEvents()
    assert not window.board.grab().isNull()
    finish_motion(window)
    assert window.board._block_hidden
    assert window.next_stage_button.isVisible()
    assert "Stage complete" in window.status_heading.text()
    window.play(Action.RIGHT)
    assert window.board._block_hidden


def test_void_fall_renders_below_platform_and_finishes_lost(window, app):
    QTest.keyClick(window.board, Qt.Key.Key_Up)
    window.board.animation.setCurrentTime(ROLL_MS + int(FALL_MS * 0.8))
    assert window.board.phase == "fall"
    vertices = window.board._frame_meshes()[0][0].vertices
    assert max(point[2] for point in vertices) < 0
    app.processEvents()
    assert not window.board.grab().isNull()
    finish_motion(window)
    assert window.board._block_hidden
    assert window.session.status is SessionStatus.LOST
    assert "Try again" in window.status_heading.text()


def test_qt_clock_advances_and_restart_remains_responsive(window):
    QTest.keyClick(window.board, Qt.Key.Key_Right)
    window.board.animation.setDuration(1000)
    advanced = QSignalSpy(window.board.animation.valueChanged)
    assert advanced.wait(500)
    assert window.board.animation.currentTime() > 0
    assert window.board.is_animating
    QTest.mouseClick(window.restart_button, Qt.MouseButton.LeftButton)
    assert not window.board.is_animating
    assert window.session.action_count == 0


def test_closing_window_stops_animation(window):
    QTest.keyClick(window.board, Qt.Key.Key_Right)
    window.close()
    assert not window.board.is_animating


def test_overhang_lifts_the_supported_half_before_free_fall(window, app):
    QTest.keyClick(window.board, Qt.Key.Key_Up)
    assert window.board._fall_support == (Position(1, 1),)
    state = window.session.state
    source = block_meshes(state.block)[0]
    window.board.animation.setCurrentTime(ROLL_MS + FALL_MS // 4)
    assert window.board.phase == "fall"
    mesh = window.board._frame_meshes()[0][0]
    supported_vertices = [i for i, point in enumerate(source.vertices) if point[1] >= 1]
    assert all(mesh.vertices[i][2] >= BLOCK_INSET for i in supported_vertices)
    assert any(point[2] < BLOCK_INSET for point in mesh.vertices)
    assert window.session.state == state
    app.processEvents()
    assert not window.board.grab().isNull()
    window.restart()
    assert window.board._fall_support == ()
    assert not window.board.is_animating


def test_bridge_closure_selects_the_actual_support_edge(app, make_level):
    bridge = Bridge("b", (Position(3, 4),), True)
    switch = Switch("s", Position(3, 5), SwitchKind.SOFT, BridgeEffect(EffectMode.TOGGLE, ("b",)))
    level = make_level(bridges=(bridge,), switches=(switch,))
    custom = MainWindow([level])
    try:
        custom.session.state = GameState(NormalBlock(4, 4, Orientation.HORIZONTAL), 1)
        custom._refresh()
        custom.show()
        QTest.keyClick(custom.board, Qt.Key.Key_Up)
        assert custom.board._fall_support == (Position(3, 5),)
        custom.board.animation.setCurrentTime(ROLL_MS + BRIDGE_MS + FALL_MS // 4)
        mesh = custom.board._frame_meshes()[0][0]
        below = [point for point in mesh.vertices if point[2] < BLOCK_INSET]
        assert below
        assert all(point[0] <= 5 for point in below)
        app.processEvents()
        assert not custom.board.grab().isNull()
        finish_motion(custom)
        assert custom.session.status is SessionStatus.LOST
    finally:
        custom.close()
        custom.deleteLater()
        app.processEvents()
