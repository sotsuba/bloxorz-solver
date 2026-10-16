"""Presentation-only solid geometry for rigid rolling, falling and bridge hinges."""

from dataclasses import dataclass, replace
from math import cos, pi, sin

from bloxorz.domain.models import Action, BlockState, NormalBlock, Orientation, Position, SplitBlock

Point3 = tuple[float, float, float]
BLOCK_INSET = 0.04
FACES = ((4, 5, 6, 7), (3, 2, 1, 0), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))


@dataclass(frozen=True)
class Mesh:
    """Eight cuboid vertices with optional cube identity and selection."""

    vertices: tuple[Point3, ...]
    label: str = ""
    active: bool = False


def cuboid(
    col: float, row: float, width: float, depth: float, height: float, *, base: float = 0
) -> tuple[Point3, ...]:
    """Build consistently indexed vertices, without applying game rules."""
    return tuple(
        (c, r, z)
        for z in (base, base + height)
        for c, r in ((col, row), (col + width, row), (col + width, row + depth), (col, row + depth))
    )


def block_meshes(block: BlockState) -> tuple[Mesh, ...]:
    """Represent the supplied state as an intact timber or two unit cubes."""
    if isinstance(block, SplitBlock):
        return tuple(
            Mesh(_block_vertices(pos.col, pos.row, 1, 1, 1), label, block.active_cube == index)
            for index, (pos, label) in enumerate(((block.cube_a, "A"), (block.cube_b, "B")))
        )
    width = 2 if block.orientation is Orientation.HORIZONTAL else 1
    depth = 2 if block.orientation is Orientation.VERTICAL else 1
    height = 2 if block.orientation is Orientation.STANDING else 1
    return (Mesh(_block_vertices(block.col, block.row, width, depth, height)),)


def _block_vertices(col, row, width, depth, height) -> tuple[Point3, ...]:
    """Inset all local axes equally so a quarter-turn has exact endpoints."""
    inset = BLOCK_INSET
    return cuboid(
        col + inset,
        row + inset,
        width - 2 * inset,
        depth - 2 * inset,
        height - 2 * inset,
        base=inset,
    )


def rotate_point(point: Point3, pivot: Point3, action: Action, angle: float) -> Point3:
    """Rotate around a horizontal contact edge in the requested direction."""
    col, row, z = point
    axis = 0 if action in (Action.LEFT, Action.RIGHT) else 1
    direction = 1 if action in (Action.RIGHT, Action.DOWN) else -1
    theta = angle * direction
    coordinate = point[axis] - pivot[axis]
    vertical = z - pivot[2]
    moved = pivot[axis] + coordinate * cos(theta) + vertical * sin(theta)
    height = pivot[2] - coordinate * sin(theta) + vertical * cos(theta)
    return (moved, row, height) if axis == 0 else (col, moved, height)


def roll_meshes(block: BlockState, action: Action, progress: float) -> tuple[Mesh, ...]:
    """Rotate only the controlled solid by a rigid ninety-degree turn."""
    meshes = block_meshes(block)
    moving_index = block.active_cube if isinstance(block, SplitBlock) else 0
    mesh = meshes[moving_index]
    axis = 0 if action in (Action.LEFT, Action.RIGHT) else 1
    values = [point[axis] for point in mesh.vertices]
    edge = (
        max(values) + BLOCK_INSET
        if action in (Action.RIGHT, Action.DOWN)
        else min(values) - BLOCK_INSET
    )
    pivot = (edge, 0, 0) if axis == 0 else (0, edge, 0)
    rotated = replace(
        mesh,
        vertices=tuple(rotate_point(p, pivot, action, progress * pi / 2) for p in mesh.vertices),
    )
    return tuple(rotated if index == moving_index else item for index, item in enumerate(meshes))


def drop_meshes(
    meshes: tuple[Mesh, ...], progress: float, *, tumble: Action | None = None
) -> tuple[Mesh, ...]:
    """Accelerate downward, optionally retaining a little rolling momentum."""
    fallen = []
    for mesh in meshes:
        center = tuple(sum(p[axis] for p in mesh.vertices) / 8 for axis in range(3))
        points = mesh.vertices
        if tumble:
            points = tuple(rotate_point(p, center, tumble, progress * 0.55) for p in points)
        fallen.append(
            replace(
                mesh, vertices=tuple((c, r, z - 4.8 * progress * progress) for c, r, z in points)
            )
        )
    return tuple(fallen)


def fall_meshes(
    block: BlockState, support: tuple[Position, ...], progress: float, *, tumble: Action
) -> tuple[Mesh, ...]:
    """Tip a partly supported block outwards, or drop only unsupported solids."""
    meshes = block_meshes(block)
    if isinstance(block, NormalBlock) and len(support) == 1:
        if block.orientation is Orientation.HORIZONTAL:
            direction = Action.RIGHT if support[0].col == block.col else Action.LEFT
            pivot = (block.col + 1, block.row + 0.5, 0)
            return (_tip_and_drop(meshes[0], pivot, direction, progress),)
        if block.orientation is Orientation.VERTICAL:
            direction = Action.DOWN if support[0].row == block.row else Action.UP
            pivot = (block.col + 0.5, block.row + 1, 0)
            return (_tip_and_drop(meshes[0], pivot, direction, progress),)
    if isinstance(block, SplitBlock):
        return tuple(
            mesh if cell in support else drop_meshes((mesh,), progress, tumble=tumble)[0]
            for cell, mesh in zip((block.cube_a, block.cube_b), meshes, strict=True)
        )
    return drop_meshes(meshes, progress, tumble=tumble)


def _tip_and_drop(mesh: Mesh, pivot: Point3, direction: Action, progress: float) -> Mesh:
    """Lift the supported half around the floor edge before releasing the block."""
    tipping = min(1.0, progress * 2)
    angle = tipping * tipping * (3 - 2 * tipping) * pi / 2
    tipped = replace(
        mesh, vertices=tuple(rotate_point(p, pivot, direction, angle) for p in mesh.vertices)
    )
    if progress <= 0.5:
        return tipped
    falling = (progress - 0.5) * 2
    dropped = drop_meshes((tipped,), falling)[0]
    center = tuple(sum(p[axis] for p in dropped.vertices) / 8 for axis in range(3))
    axis = 0 if direction in (Action.LEFT, Action.RIGHT) else 1
    sign = 1 if direction in (Action.RIGHT, Action.DOWN) else -1
    points = []
    for point in dropped.vertices:
        rotated = list(rotate_point(point, center, direction, 0.55 * falling * falling))
        # Drift exceeds the growing sideways extent, keeping the solid beyond the support edge.
        rotated[axis] += sign * 0.65 * falling * falling
        points.append(tuple(rotated))
    return replace(mesh, vertices=tuple(points))


def bridge_vertices(
    col: float, row: float, openness: float, thickness: float
) -> tuple[Point3, ...]:
    """Hinge a bridge plate below the floor and unfold it to a flat surface."""
    points = cuboid(col + 0.025, row + 0.025, 0.95, 0.95, thickness, base=-thickness)
    return tuple(rotate_point(p, (0, row, 0), Action.DOWN, (1 - openness) * pi / 2) for p in points)


def face_normal(points: tuple[Point3, ...]) -> Point3:
    """Compute an outward normal from a consistently wound polygon."""
    a = tuple(points[1][axis] - points[0][axis] for axis in range(3))
    b = tuple(points[2][axis] - points[0][axis] for axis in range(3))
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def clip_height(points: tuple[Point3, ...], *, above: bool = True) -> tuple[Point3, ...]:
    """Clip a face at floor height so sinking timber cannot cover the rim."""
    if not points:
        return ()
    clipped = []
    previous = points[-1]
    for current in points:
        old_inside = previous[2] >= 0 if above else previous[2] <= 0
        inside = current[2] >= 0 if above else current[2] <= 0
        if inside != old_inside:
            ratio = -previous[2] / (current[2] - previous[2])
            clipped.append(
                (
                    previous[0] + ratio * (current[0] - previous[0]),
                    previous[1] + ratio * (current[1] - previous[1]),
                    0.0,
                )
            )
        if inside:
            clipped.append(current)
        previous = current
    return tuple(clipped)
