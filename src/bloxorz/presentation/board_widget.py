"""Projected 2.5D board, rigid motion effects and focused keyboard input."""

from functools import lru_cache
from math import cos, floor, pi, sqrt

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from bloxorz.domain.engine import bridge_is_open, supported_cells
from bloxorz.domain.models import (
    Action,
    EventType,
    GameState,
    Level,
    Outcome,
    Position,
    SwitchKind,
    TransitionResult,
)
from bloxorz.presentation.motion import (
    BLOCK_INSET,
    FACES,
    Mesh,
    block_meshes,
    bridge_vertices,
    clip_height,
    drop_meshes,
    face_normal,
    fall_meshes,
    roll_meshes,
)

ROW_SKEW = 0.48
ROW_DROP = 0.62
COLUMN_RISE = 0.18
HEIGHT_SCALE = 0.95
FLOOR_DEPTH = 0.16
ROLL_MS = 230
TRANSFORM_MS = 180
BRIDGE_MS = 300
FALL_MS = 540


def _surface_noise(x: float, y: float) -> float:
    """Interpolate deterministic noise for connected, irregular patina patches."""
    col, row = floor(x), floor(y)
    u, v = x - col, y - row
    u, v = u * u * (3 - 2 * u), v * v * (3 - 2 * v)
    values = []
    for dc, dr in ((0, 0), (1, 0), (0, 1), (1, 1)):
        seed = ((col + dc) * 374761393 + (row + dr) * 668265263) & 0xFFFFFFFF
        seed = ((seed ^ (seed >> 13)) * 1274126177) & 0xFFFFFFFF
        values.append((seed ^ (seed >> 16)) / 0xFFFFFFFF)
    top = values[0] + (values[1] - values[0]) * u
    bottom = values[2] + (values[3] - values[2]) * u
    return top + (bottom - top) * v


@lru_cache(maxsize=4)
def _patina_texture(width: int, height: int) -> QImage:
    """Cache a rust-and-charcoal material in object space, independently of frames."""
    pixels = bytearray()
    image_width, image_height = width * 64, height * 64
    for row in range(image_height):
        for col in range(image_width):
            x, y = col / 64 + 2.7, row / 64 + 5.3
            noise = (
                0.65 * _surface_noise(x * 3, y * 3)
                + 0.25 * _surface_noise(x * 7, y * 7)
                + 0.1 * _surface_noise(x * 17, y * 17)
            )
            blend = max(0.0, min(1.0, (noise - 0.43) / 0.13))
            blend = blend * blend * (3 - 2 * blend)
            grain = ((col * 73 + row * 137 + col * row * 19) % 17) - 8
            pixels.extend(
                (
                    int(166 - 49 * blend) + grain,
                    int(116 + 16 * blend) + grain,
                    int(81 + 67 * blend) + grain,
                    255,
                )
            )
    return QImage(
        bytes(pixels), image_width, image_height, image_width * 4, QImage.Format.Format_RGBA8888
    ).copy()


KEY_ACTIONS = {
    Qt.Key.Key_Up: Action.UP,
    Qt.Key.Key_W: Action.UP,
    Qt.Key.Key_Down: Action.DOWN,
    Qt.Key.Key_S: Action.DOWN,
    Qt.Key.Key_Left: Action.LEFT,
    Qt.Key.Key_A: Action.LEFT,
    Qt.Key.Key_Right: Action.RIGHT,
    Qt.Key.Key_D: Action.RIGHT,
    Qt.Key.Key_Space: Action.SWAP_ACTIVE_CUBE,
}


class BoardWidget(QWidget):
    """Render real block proportions through a fixed oblique projection."""

    action_requested = Signal(object)
    restart_requested = Signal()
    animation_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level: Level | None = None
        self.state: GameState | None = None
        self.lost = False
        self._block_hidden = False
        self._previous: GameState | None = None
        self._move: TransitionResult | None = None
        self._action: Action | None = None
        self._fall_support: tuple[Position, ...] = ()
        self._progress = 0.0
        self._transform_ms = self._bridge_ms = self._fall_ms = 0
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._advance_animation)
        self.animation.finished.connect(self._finish_animation)
        self._view = (1.0, 0.0, 0.0)
        self._ground = QPainterPath()
        self._platform = QPainterPath()
        self.setMinimumSize(300, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Bloxorz game board")
        self.setAccessibleDescription(
            "An angled view of the platform and block. "
            "Arrow keys or WASD to roll. Space changes the active cube. R restarts."
        )

    def display(
        self, level: Level, state: GameState, *, lost: bool = False, won: bool = False
    ) -> None:
        """Cancel pending effects and display an authoritative session snapshot."""
        self.cancel_animation()
        self.level, self.state, self.lost = level, state, lost
        self._block_hidden = lost or won
        self.update()

    @property
    def is_animating(self) -> bool:
        """Keep movement locked until the entire move and its effects finish."""
        return self._move is not None

    @property
    def phase(self) -> str:
        """Identify the visible stage of the current Qt animation timeline."""
        if not self.is_animating:
            return ""
        elapsed = self._progress * self.animation.duration()
        if elapsed < ROLL_MS:
            return "roll"
        if elapsed < ROLL_MS + self._transform_ms:
            return "transform"
        if elapsed < ROLL_MS + self._transform_ms + self._bridge_ms:
            return "bridge"
        return "fall" if self._fall_ms else "roll"

    def animate_move(
        self, level: Level, previous: GameState, action: Action, result: TransitionResult
    ) -> None:
        """Animate a committed engine result without changing its rules or state."""
        self.display(level, result.next_state)
        self._previous, self._action, self._move = previous, action, result
        self._fall_support = (
            supported_cells(level, result.next_state) if result.outcome is Outcome.LOST else ()
        )
        self._transform_ms = (
            TRANSFORM_MS
            if any(
                event.kind in (EventType.BLOCK_SPLIT, EventType.BLOCK_MERGED)
                for event in result.events
            )
            else 0
        )
        self._bridge_ms = BRIDGE_MS if previous.bridge_mask != result.next_state.bridge_mask else 0
        self._fall_ms = FALL_MS if result.outcome in (Outcome.WON, Outcome.LOST) else 0
        self.animation.setDuration(ROLL_MS + self._transform_ms + self._bridge_ms + self._fall_ms)
        self.animation.start()

    def cancel_animation(self) -> None:
        """Stop immediately so resets and window closure cannot replay old effects."""
        self.animation.stop()
        self._previous = self._move = self._action = None
        self._fall_support = ()
        self._progress = 0.0

    def _advance_animation(self, value: float) -> None:
        """Repaint a new frame from Qt's nonblocking animation clock."""
        self._progress = float(value)
        self.update()

    def _finish_animation(self) -> None:
        """Hide terminal timber and notify the window to unlock valid controls."""
        if self._move is None:
            return
        self._block_hidden = self._move.outcome in (Outcome.WON, Outcome.LOST)
        self.cancel_animation()
        self.update()
        self.animation_finished.emit()

    def _fraction(self, start_ms: int, duration_ms: int) -> float:
        """Clamp local phase progress even while another phase is active."""
        if not duration_ms:
            return 1.0
        return max(
            0.0, min(1.0, (self._progress * self.animation.duration() - start_ms) / duration_ms)
        )

    @staticmethod
    def _ease(progress: float) -> float:
        """Slow the start and landing without changing rigid block dimensions."""
        return (1 - cos(pi * progress)) / 2

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle game keys while preserving ordinary Tab focus navigation."""
        action = KEY_ACTIONS.get(event.key())
        if action:
            self.action_requested.emit(action)
            event.accept()
        elif event.key() == Qt.Key.Key_R:
            self.restart_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        """Draw floating platforms and a shaded block at its actual height."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        backdrop = QLinearGradient(0, 0, self.width(), self.height())
        backdrop.setColorAt(0, QColor("#29465D"))
        backdrop.setColorAt(0.55, QColor("#172D42"))
        backdrop.setColorAt(1, QColor("#101E2D"))
        painter.fillRect(self.rect(), backdrop)
        if self.level is not None and self.state is not None:
            self._fit_projection()
            self._draw_grid(painter)
            self._draw_block(painter)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#527184"), 0.8, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), 8, 8)
        painter.end()

    def _fit_projection(self) -> None:
        """Reserve upright-block clearance without changing zoom after a move."""
        points = []
        for row, tiles in enumerate(self.level.grid):
            for col, tile in enumerate(tiles):
                if tile == "#" and Position(row, col) not in self.level.bridge_at:
                    continue
                for c, r in ((col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)):
                    for z in (-0.35, 2.3):
                        points.append(
                            (c + ROW_SKEW * r, ROW_DROP * r - COLUMN_RISE * c - HEIGHT_SCALE * z)
                        )
        left, right = min(p[0] for p in points), max(p[0] for p in points)
        top, bottom = min(p[1] for p in points), max(p[1] for p in points)
        scale = min(
            (self.width() - 52) / (right - left), (self.height() - 52) / (bottom - top), 100
        )
        self._view = (
            scale,
            self.width() / 2 - scale * (left + right) / 2,
            self.height() / 2 - scale * (top + bottom) / 2,
        )

    def _project(self, col: float, row: float, height: float = 0) -> QPointF:
        """Project one board-space coordinate; positive height goes upward."""
        scale, left, top = self._view
        return QPointF(
            left + scale * (col + ROW_SKEW * row),
            top + scale * (ROW_DROP * row - COLUMN_RISE * col - HEIGHT_SCALE * height),
        )

    def _surface_transform(self) -> QTransform:
        """Keep symbols and material marks flush with the inclined floor."""
        scale, left, top = self._view
        return QTransform(
            scale, -COLUMN_RISE * scale, ROW_SKEW * scale, ROW_DROP * scale, left, top
        )

    def _quad(self, footprint: QRectF, height: float = 0) -> QPolygonF:
        """Project four footprint corners in a consistent winding order."""
        return QPolygonF(
            [
                self._project(footprint.left(), footprint.top(), height),
                self._project(footprint.right(), footprint.top(), height),
                self._project(footprint.right(), footprint.bottom(), height),
                self._project(footprint.left(), footprint.bottom(), height),
            ]
        )

    def _draw_prism(
        self,
        painter: QPainter,
        footprint: QRectF,
        height: float,
        colors: tuple[str, str, str],
        *,
        base: float = 0,
    ) -> tuple[QPolygonF, QPolygonF, QPolygonF]:
        """Paint the two camera-facing walls and the top of a rectangular solid."""
        bottom = self._quad(footprint, base)
        top = self._quad(footprint, base + height)
        left = QPolygonF([bottom[0], bottom[3], top[3], top[0]])
        front = QPolygonF([bottom[3], bottom[2], top[2], top[3]])
        painter.setPen(
            QPen(
                QColor("#596773"),
                0.7,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.SquareCap,
                Qt.PenJoinStyle.MiterJoin,
            )
        )
        for face, color in ((left, colors[1]), (front, colors[2]), (top, colors[0])):
            painter.setBrush(QColor(color))
            painter.drawPolygon(face)
            silhouette = QPainterPath()
            silhouette.addPolygon(face)
            self._platform = self._platform.united(silhouette)
        return top, left, front

    def _draw_grid(self, painter: QPainter) -> None:
        """Paint distant tiles first so near platform edges hide rear edges."""
        tiles = [
            (Position(row, col), tile, self.level.bridge_at.get(Position(row, col)))
            for row, line in enumerate(self.level.grid)
            for col, tile in enumerate(line)
            if tile != "#" or Position(row, col) in self.level.bridge_at
        ]
        tiles.sort(key=lambda item: item[0].row - ROW_SKEW * item[0].col)
        self._ground = QPainterPath()
        self._platform = QPainterPath()
        self._ground.setFillRule(Qt.FillRule.WindingFill)
        for pos, _, bridge in tiles:
            if bridge is None or self._bridge_openness(bridge) >= 0.999:
                self._ground.addPolygon(self._quad(QRectF(pos.col, pos.row, 1, 1)))
        painter.setPen(
            QPen(
                QColor(3, 10, 18, 25),
                18,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(QColor(3, 10, 18, 60))
        painter.drawPath(self._ground.translated(6, 16))
        for pos, tile, bridge in tiles:
            if bridge:
                self._draw_bridge(painter, pos, self._bridge_openness(bridge))
            else:
                self._draw_tile(painter, pos, tile)
            switch = self.level.switch_at.get(pos)
            if switch:
                self._draw_switch(painter, pos, switch.kind)

    def _draw_tile(self, painter: QPainter, pos: Position, tile: str) -> None:
        """Extrude stone slabs and retain a visible seam around every cell."""
        footprint = QRectF(pos.col + 0.012, pos.row + 0.012, 0.976, 0.976)
        stone = "#D8DFE2" if (pos.row * 3 + pos.col) % 4 else "#C9D2D8"
        colors = ("#E3A17A", "#985B42", "#B87955") if tile == "F" else (stone, "#73818A", "#99A6AE")
        self._draw_prism(painter, footprint, FLOOR_DEPTH, colors, base=-FLOOR_DEPTH)
        self._draw_tile_marks(painter, pos, tile)
        if tile == "G":
            self._draw_goal(painter, pos)

    def _draw_tile_marks(self, painter: QPainter, pos: Position, tile: str) -> None:
        """Use quiet stone veins and cracks to distinguish floor from fragile."""
        painter.save()
        painter.setWorldTransform(self._surface_transform())
        painter.setClipRect(QRectF(pos.col + 0.04, pos.row + 0.04, 0.92, 0.92))
        if tile == "F":
            painter.setPen(QPen(QColor("#A76243"), 0.022))
            crack = QPolygonF(
                [
                    QPointF(pos.col + 0.12, pos.row + 0.08),
                    QPointF(pos.col + 0.44, pos.row + 0.35),
                    QPointF(pos.col + 0.36, pos.row + 0.54),
                    QPointF(pos.col + 0.69, pos.row + 0.70),
                    QPointF(pos.col + 0.61, pos.row + 0.96),
                ]
            )
            painter.drawPolyline(crack)
            painter.drawLine(
                QPointF(pos.col + 0.36, pos.row + 0.54), QPointF(pos.col + 0.10, pos.row + 0.73)
            )
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 75), 0.016))
            offset = ((pos.col * 7 + pos.row * 3) % 5) * 0.07
            painter.drawLine(
                QPointF(pos.col + 0.08, pos.row + 0.25 + offset),
                QPointF(pos.col + 0.88, pos.row + 0.50 + offset),
            )
            if tile == "S":
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#879CA7"), 0.022, Qt.PenStyle.DashLine))
                painter.drawEllipse(QPointF(pos.col + 0.5, pos.row + 0.5), 0.22, 0.22)
        painter.restore()

    def _draw_goal(self, painter: QPainter, pos: Position) -> None:
        """Cut a dark square hole with recessed interior walls into the slab."""
        opening = QRectF(pos.col + 0.025, pos.row + 0.025, 0.95, 0.95)
        rim, bottom = self._quad(opening), self._quad(opening, -0.32)
        clip = QPainterPath()
        clip.addPolygon(rim)
        painter.save()
        painter.setClipPath(clip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#09131C"))
        painter.drawPolygon(rim)
        painter.setBrush(QColor("#52636C"))
        painter.drawPolygon(QPolygonF([rim[0], rim[1], bottom[1], bottom[0]]))
        painter.setBrush(QColor("#344853"))
        painter.drawPolygon(QPolygonF([rim[1], rim[2], bottom[2], bottom[1]]))
        painter.restore()
        painter.setPen(QPen(QColor("#52616B"), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(rim)

    def _bridge_openness(self, bridge_id: str) -> float:
        """Animate old-to-new passability only after the block lands."""
        target = float(bridge_is_open(self.level, self.state, bridge_id))
        if not self.is_animating:
            return target
        previous = float(bridge_is_open(self.level, self._previous, bridge_id))
        progress = self._ease(self._fraction(ROLL_MS + self._transform_ms, self._bridge_ms))
        return previous + (target - previous) * progress

    def _draw_bridge(self, painter: QPainter, pos: Position, openness: float) -> None:
        """Unfold a hinged plate into place or fold it down into the void."""
        footprint = QRectF(pos.col + 0.025, pos.row + 0.025, 0.95, 0.95)
        if openness >= 0.999:
            self._draw_prism(
                painter,
                footprint,
                FLOOR_DEPTH,
                ("#70B8B0", "#316F73", "#4B8E8B"),
                base=-FLOOR_DEPTH,
            )
        elif openness > 0.001:
            vertices = bridge_vertices(pos.col, pos.row, openness, FLOOR_DEPTH)
            painter.save()
            painter.setOpacity(0.35 + 0.65 * openness)
            for _, points, _, _ in self._visible_faces(((Mesh(vertices), 1.0),), inset=0):
                polygon = self._polygon(points)
                painter.setBrush(QColor("#589D98"))
                painter.setPen(QPen(QColor("#316F73"), 1))
                painter.drawPolygon(polygon)
            painter.restore()
        if openness < 0.999:
            painter.save()
            painter.setOpacity(1 - openness)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#60A9A7"), 1.5, Qt.PenStyle.DashLine))
            painter.drawPolygon(self._quad(footprint))
            painter.restore()
        if openness >= 0.999:
            painter.save()
            painter.setWorldTransform(self._surface_transform())
            painter.setPen(QPen(QColor("#387D7D"), 0.035))
            for offset in (0.25, 0.5, 0.75):
                painter.drawLine(
                    QPointF(pos.col + 0.13, pos.row + offset),
                    QPointF(pos.col + 0.87, pos.row + offset),
                )
            painter.restore()

    def _draw_switch(self, painter: QPainter, pos: Position, kind: SwitchKind) -> None:
        """Place the circle, X and bracket symbols on the projected tile surface."""
        painter.save()
        painter.setWorldTransform(self._surface_transform())
        center = QPointF(pos.col + 0.5, pos.row + 0.5)
        painter.setPen(QPen(QColor("#666A69"), 0.035))
        painter.setBrush(QColor("#B0B1A7"))
        if kind is SwitchKind.SPLIT:
            painter.setBrush(QColor("#A79AC7"))
            painter.setPen(QPen(QColor("#6B5D8E"), 0.025))
            painter.drawRoundedRect(QRectF(pos.col + 0.21, pos.row + 0.19, 0.58, 0.62), 0.06, 0.06)
            painter.setPen(QPen(QColor("#F2EDF9"), 0.05))
            painter.drawArc(QRectF(pos.col + 0.29, pos.row + 0.29, 0.20, 0.42), 90 * 16, 180 * 16)
            painter.drawArc(QRectF(pos.col + 0.51, pos.row + 0.29, 0.20, 0.42), -90 * 16, 180 * 16)
        else:
            painter.drawEllipse(center, 0.27, 0.27)
            painter.setBrush(QColor("#CACBC1"))
            painter.drawEllipse(center, 0.20, 0.20)
            painter.setPen(
                QPen(QColor("#545B5C"), 0.05, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            )
            if kind is SwitchKind.HEAVY:
                painter.drawLine(center + QPointF(-0.12, -0.12), center + QPointF(0.12, 0.12))
                painter.drawLine(center + QPointF(-0.12, 0.12), center + QPointF(0.12, -0.12))
            else:
                painter.setBrush(QColor("#747D7B"))
                painter.drawEllipse(center, 0.07, 0.07)
        painter.restore()

    def _frame_meshes(self) -> tuple[tuple[Mesh, float], ...]:
        """Select rigid rolling, split/merge fading, or accelerated falling geometry."""
        if not self.is_animating:
            return tuple((mesh, 1.0) for mesh in block_meshes(self.state.block))
        elapsed = self._progress * self.animation.duration()
        if elapsed < ROLL_MS:
            meshes = roll_meshes(
                self._previous.block, self._action, self._ease(self._fraction(0, ROLL_MS))
            )
            return tuple((mesh, 1.0) for mesh in meshes)
        final = block_meshes(self.state.block)
        transform = self._fraction(ROLL_MS, self._transform_ms)
        if self._transform_ms and transform < 1:
            source = roll_meshes(self._previous.block, self._action, 1)
            return tuple((mesh, 1 - transform) for mesh in source) + tuple(
                (mesh, transform) for mesh in final
            )
        if self._fall_ms:
            progress = self._fraction(ROLL_MS + self._transform_ms + self._bridge_ms, self._fall_ms)
            lost = self._move.outcome is Outcome.LOST
            meshes = (
                fall_meshes(self.state.block, self._fall_support, progress, tumble=self._action)
                if lost
                else drop_meshes(final, progress)
            )
            opacity = min(1.0, 2 * (1 - progress)) if lost else 1.0
            return tuple((mesh, opacity) for mesh in meshes)
        return tuple((mesh, 1.0) for mesh in final)

    def _visible_faces(self, meshes, *, inset: float = BLOCK_INSET):
        """Cull back faces and sort visible faces along the camera direction."""
        camera = (-ROW_SKEW, 1, (ROW_DROP + COLUMN_RISE * ROW_SKEW) / HEIGHT_SCALE)
        faces = []
        for mesh, opacity in meshes:
            points = tuple((c, r, z - inset) for c, r, z in mesh.vertices)
            for indices in FACES:
                face = tuple(points[index] for index in indices)
                normal = face_normal(face)
                if sum(normal[axis] * camera[axis] for axis in range(3)) <= 1e-8:
                    continue
                depth = sum(sum(p[axis] * camera[axis] for axis in range(3)) for p in face) / 4
                faces.append((depth, face, mesh, opacity))
        return sorted(faces, key=lambda item: item[0])

    def _polygon(self, points) -> QPolygonF:
        """Project arbitrary world-space faces, including clipped ones."""
        return QPolygonF([self._project(c, r, z) for c, r, z in points])

    def _draw_block(self, painter: QPainter) -> None:
        """Paint a mottled rust-and-charcoal block with correct floor occlusion."""
        if self._block_hidden:
            return
        meshes = self._frame_meshes()
        falling = self.is_animating and self.phase == "fall"
        if not falling:
            for mesh, opacity in meshes:
                columns = [point[0] for point in mesh.vertices]
                rows = [point[1] for point in mesh.vertices]
                footprint = QRectF(
                    min(columns), min(rows), max(columns) - min(columns), max(rows) - min(rows)
                )
                painter.save()
                painter.setOpacity(opacity)
                self._draw_block_shadow(painter, footprint, max(p[2] for p in mesh.vertices))
                painter.restore()
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        outside = outside.subtracted(self._platform)
        for _, face, mesh, opacity in self._visible_faces(meshes):
            if not falling:
                self._paint_block_face(painter, face, face, mesh, opacity)
                continue
            if self._move.outcome is Outcome.LOST:
                painter.save()
                painter.setClipPath(outside, Qt.ClipOperation.IntersectClip)
                self._paint_block_face(painter, face, clip_height(face, above=False), mesh, opacity)
                painter.restore()
            self._paint_block_face(painter, face, clip_height(face), mesh, opacity)

    def _paint_block_face(self, painter, original, clipped, mesh: Mesh, opacity: float) -> None:
        """Shade the rust base and attach its patina to the rotating face."""
        if len(clipped) < 3 or opacity <= 0:
            return
        polygon = self._polygon(clipped)
        normal = face_normal(original)
        magnitude = sqrt(sum(value * value for value in normal))
        unit = tuple(value / magnitude for value in normal)
        light = max(0.0, min(1.0, unit[2] + 0.5 * unit[1] - 0.08 * unit[0]))
        color = QColor(int(83 + 69 * light), int(56 + 57 * light), int(41 + 44 * light))
        painter.save()
        painter.setOpacity(opacity)
        painter.setPen(QPen(QColor("#3E3935"), 1.1))
        painter.setBrush(color)
        painter.drawPolygon(polygon)
        self._draw_block_texture(painter, original, polygon, light)
        if unit[2] > 0.6:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(QColor("#FFE1AE" if mesh.active else "#B19077"), 2.4 if mesh.active else 0.9)
            )
            painter.drawPolygon(polygon)
        if mesh.label and unit[1] > 0.8:
            self._draw_cube_label(painter, polygon, mesh.label, mesh.active)
        painter.restore()

    def _draw_block_texture(
        self, painter: QPainter, face, polygon: QPolygonF, light: float
    ) -> None:
        """Attach a cached mottled material to the rotating face's local axes."""
        projected = self._polygon(face)
        origin, along, down = projected[0], projected[1] - projected[0], projected[3] - projected[0]
        if abs(along.x() * down.y() - along.y() * down.x()) < 4:
            return
        width = sqrt(sum((face[1][axis] - face[0][axis]) ** 2 for axis in range(3)))
        height = sqrt(sum((face[3][axis] - face[0][axis]) ** 2 for axis in range(3)))
        painter.save()
        clip = QPainterPath()
        clip.addPolygon(polygon)
        painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        painter.setWorldTransform(
            QTransform(along.x(), along.y(), down.x(), down.y(), origin.x(), origin.y())
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(
            QRectF(0, 0, 1, 1), _patina_texture(max(1, round(width)), max(1, round(height)))
        )
        painter.fillRect(QRectF(0, 0, 1, 1), QColor(0, 0, 0, int(128 * (1 - light))))
        painter.restore()

    def _draw_block_shadow(self, painter: QPainter, footprint: QRectF, height: float) -> None:
        """Clip a directional cast shadow to supported floor surfaces."""
        base = self._quad(footprint)
        shifted = base.translated(
            QPointF(height * self._view[0] * 0.42, height * self._view[0] * 0.18)
        )
        shadow = QPainterPath()
        shadow.setFillRule(Qt.FillRule.WindingFill)
        shadow.addPolygon(base)
        shadow.addPolygon(shifted)
        for index in range(4):
            following = (index + 1) % 4
            shadow.addPolygon(
                QPolygonF([base[index], base[following], shifted[following], shifted[index]])
            )
        painter.save()
        painter.setClipPath(self._ground)
        painter.fillPath(shadow, QColor(5, 12, 18, 85))
        painter.restore()

    def _draw_cube_label(
        self, painter: QPainter, face: QPolygonF, label: str, active: bool
    ) -> None:
        """Keep cube identities readable on the front wall."""
        center = QPointF(
            sum(point.x() for point in face) / len(face),
            sum(point.y() for point in face) / len(face),
        )
        font = QFont(self.font())
        font.setPixelSize(max(12, int(self._view[0] * 0.28)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFF2D5" if active else "#E0D2BF"))
        painter.drawText(
            QRectF(center.x() - 15, center.y() - 15, 30, 30), Qt.AlignmentFlag.AlignCenter, label
        )
