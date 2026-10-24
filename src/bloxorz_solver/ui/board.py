"""Project and render a board animation using Pygame surfaces."""

from math import cos, pi, sin, sqrt

import pygame

from bloxorz_solver.game.state import Outcome, Position, SwitchKind
from bloxorz_solver.ui.animation import BoardAnimation
from bloxorz_solver.ui.motion import (
    BLOCK_INSET,
    FACES,
    Mesh,
    Point3,
    bridge_vertices,
    clip_height,
    cuboid,
    face_normal,
)
from bloxorz_solver.ui.rendering import (
    COLUMN_RISE,
    HEIGHT_SCALE,
    ROW_DROP,
    ROW_SKEW,
    depth,
    project,
    shade,
    visible,
)

FLOOR_DEPTH = 0.38


class Board:
    """Render the supplied animation; never advance time or mutate game state."""

    def __init__(self, animation: BoardAnimation):
        self.animation = animation
        self._view = (1.0, 0.0, 0.0)
        self._label_fonts: dict[int, pygame.font.Font] = {}
        self._level = None
        self._size = None
        self._platform_key = None
        self._platform = None
        self._occlusion = None
        self._block_layer = None
        self._below_layer = None

    def _fit_view(self, rect: pygame.Rect) -> None:
        points = [
            (c + ROW_SKEW * r, ROW_DROP * r - COLUMN_RISE * c - HEIGHT_SCALE * z)
            for c in (-1, self.animation.level.width + 1)
            for r in (-1, self.animation.level.height + 1)
            for z in (-1, 2)
        ]
        left, right = min(p[0] for p in points), max(p[0] for p in points)
        top, bottom = min(p[1] for p in points), max(p[1] for p in points)
        scale = min((rect.width - 24) / (right - left), (rect.height - 24) / (bottom - top), 100)
        self._view = (
            scale,
            rect.centerx - scale * (left + right) / 2,
            rect.centery - scale * (top + bottom) / 2,
        )

    def _project(self, col: float, row: float, height: float = 0) -> tuple[float, float]:
        return project((col, row, height), self._view)

    def _polygon(self, surface, points, color, *, outline=None):
        if len(points) < 3:
            return
        projected = [self._project(*p) for p in points]
        pygame.draw.polygon(surface, color, projected)
        if outline:
            pygame.draw.lines(surface, outline, True, projected,
                              max(1, round(self._view[0] * 0.025)))

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill((0, 0, 0, 0))
        if self.animation.level is None:
            return
        level, size = self.animation.level, surface.get_size()
        if self._level is not level or self._size != size:
            self._level, self._size = level, size
            self._fit_view(surface.get_rect())
            self._platform_key = None
            self._block_layer = pygame.Surface(size, pygame.SRCALPHA)
            self._below_layer = pygame.Surface(size, pygame.SRCALPHA)
        # Block motion does not change the floor. Only bridge geometry does.
        key = tuple(self.animation.bridge_openness(bridge.id) for bridge in level.bridges)
        if self._platform_key != key:
            self._platform = self._draw_platform(size)
            self._platform_key = key
            self._occlusion = None
        surface.blit(self._platform, (0, 0))
        self._draw_block(surface, self._platform)

    def _draw_platform(self, size: tuple[int, int]) -> pygame.Surface:
        platform = pygame.Surface(size, pygame.SRCALPHA)
        tiles = [
            (Position(r, c), tile, self.animation.level.bridge_at.get(Position(r, c)))
            for r, line in enumerate(self.animation.level.grid)
            for c, tile in enumerate(line)
            if tile != "#" or Position(r, c) in self.animation.level.bridge_at
        ]
        tiles.sort(key=lambda item: item[0].row - ROW_SKEW * item[0].col)
        for pos, tile, bridge in tiles:
            if bridge:
                self._draw_bridge(platform, pos, bridge)
            else:
                self._draw_tile(platform, pos, tile)
            switch = self.animation.level.switch_at.get(pos)
            if switch:
                self._draw_switch(platform, pos, switch.kind)
        return platform

    def _draw_bridge(self, surface: pygame.Surface, pos: Position, bridge: str) -> None:
        openness = self.animation.bridge_openness(bridge)
        if openness > 0.001:
            mesh = Mesh(bridge_vertices(pos.col, pos.row, openness, FLOOR_DEPTH))
            self._draw_solid(surface, mesh, (112, 184, 176))
        if openness < 0.999:
            points = [
                self._project(pos.col + c, pos.row + r) for c, r in ((0, 0), (1, 0), (1, 1), (0, 1))
            ]
            # Broken outline distinguishes an absent bridge from safe floor.
            for a, b in zip(points, points[1:] + points[:1], strict=True):
                for t in (0, 0.4, 0.8):
                    start = tuple(a[i] + (b[i] - a[i]) * t for i in (0, 1))
                    end = tuple(a[i] + (b[i] - a[i]) * min(1, t + 0.2) for i in (0, 1))
                    pygame.draw.aaline(surface, "#60A9A7", start, end)

    def _draw_tile(self, surface: pygame.Surface, pos: Position, tile: str) -> None:
        color = (232, 177, 112) if tile == "F" else (176, 201, 138)
        mesh = Mesh(
            cuboid(
                pos.col + 0.012,
                pos.row + 0.012,
                0.976,
                0.976,
                FLOOR_DEPTH,
                base=-FLOOR_DEPTH,
            )
        )
        self._draw_solid(surface, mesh, color)
        self._draw_marker(surface, pos, tile)

    def _draw_block(self, surface: pygame.Surface, platform: pygame.Surface) -> None:
        if self.animation.block_hidden:
            return
        faces = self._visible_faces(self.animation.frame_meshes())
        falling = self.animation.phase == "fall"
        # Draw below-floor fragments only outside the platform silhouette.
        if falling and self.animation.falling_outcome is Outcome.LOST:
            below = self._below_layer
            below.fill((0, 0, 0, 0))
            for _, face, mesh, opacity in faces:
                self._draw_block_face(below, face, clip_height(face, above=False), mesh, opacity)
            if self._occlusion is None:
                self._occlusion = pygame.mask.from_surface(platform).to_surface(
                    setcolor=(0, 0, 0, 255), unsetcolor=(0, 0, 0, 0)
                )
            below.blit(self._occlusion, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
            surface.blit(below, (0, 0))
        block_layer = self._block_layer
        block_layer.fill((0, 0, 0, 0))
        for _, face, mesh, opacity in faces:
            self._draw_block_face(
                block_layer, face, clip_height(face) if falling else face, mesh, opacity
            )
        surface.blit(block_layer, (0, 0))

    def _draw_solid(self, surface, mesh, color):
        for _, face, _, _ in self._visible_faces(((mesh, 1.0),), inset=0):
            self._polygon(surface, face, shade(color, face), outline="#50604A")

    def _draw_marker(self, surface, pos, tile):
        def point(c, r):
            return self._project(pos.col + c, pos.row + r)

        if tile == "G":
            opening = [
                (pos.col + c, pos.row + r, 0)
                for c, r in ((0.04, 0.04), (0.96, 0.04), (0.96, 0.96), (0.04, 0.96))
            ]
            self._polygon(surface, opening, "#09131C")
        elif tile == "F":
            pygame.draw.aalines(
                surface,
                "#A76243",
                False,
                [
                    point(c, r)
                    for c, r in (
                        (0.12, 0.08),
                        (0.44, 0.35),
                        (0.36, 0.54),
                        (0.69, 0.7),
                        (0.61, 0.96),
                    )
                ],
            )
        elif tile == "S":
            pygame.draw.circle(
                surface, "#879CA7", point(0.5, 0.5), max(2, int(self._view[0] * 0.13)), 1
            )

    def _draw_switch(self, surface, pos, kind):
        def point(c, r):
            return self._project(pos.col + c, pos.row + r)

        disk = [
            point(0.5 + 0.27 * cos(i * pi / 12), 0.5 + 0.27 * sin(i * pi / 12)) for i in range(24)
        ]
        pygame.draw.polygon(surface, "#A79AC7" if kind is SwitchKind.SPLIT else "#A3ABA4", disk)
        pygame.draw.aalines(surface, "#666A69", True, disk)
        if kind is SwitchKind.HEAVY:
            for a, b in (((0.36, 0.36), (0.64, 0.64)), ((0.36, 0.64), (0.64, 0.36))):
                pygame.draw.line(surface, "#545B5C", point(*a), point(*b), 2)
        elif kind is SwitchKind.SPLIT:
            pygame.draw.line(surface, "#F2EDF9", point(0.5, 0.25), point(0.5, 0.75), 2)
        else:
            pygame.draw.circle(
                surface, "#545B5C", point(0.5, 0.5), max(2, int(self._view[0] * 0.05))
            )

    def _draw_block_face(
        self,
        surface: pygame.Surface,
        original: tuple[Point3, ...],
        face: tuple[Point3, ...],
        mesh: Mesh,
        opacity: float,
    ) -> None:
        if len(face) < 3 or opacity <= 0:
            return
        normal = face_normal(original)
        magnitude = sqrt(sum(value * value for value in normal))
        unit = tuple(value / magnitude for value in normal)
        color = (*shade((251, 243, 224), original), int(255 * opacity))
        edge_color = (158, 94, 30) if mesh.active else (91, 82, 65)
        outline = (*edge_color, int(255 * opacity))
        self._polygon(surface, face, color, outline=outline)
        if mesh.label and unit[1] > 0.8:
            center = tuple(sum(p[i] for p in face) / len(face) for i in range(3))
            size = max(16, int(self._view[0] * 0.35))
            if size not in self._label_fonts:
                self._label_fonts[size] = pygame.font.Font(None, size)
            font = self._label_fonts[size]
            label = font.render(mesh.label, True, "#463B30")
            label.set_alpha(int(255 * opacity))
            surface.blit(label, label.get_rect(center=self._project(*center)))

    def _visible_faces(self, meshes, *, inset: float = BLOCK_INSET):
        """Cull back faces and sort visible faces along the camera direction."""
        faces = []
        for mesh, opacity in meshes:
            points = tuple((c, r, z - inset) for c, r, z in mesh.vertices)
            for indices in FACES:
                face = tuple(points[index] for index in indices)
                if not visible(face):
                    continue
                faces.append((depth(face), face, mesh, opacity))
        return sorted(faces, key=lambda item: item[0])
