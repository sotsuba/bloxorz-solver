"""Shared orthographic camera and lighting for the game board."""

from math import sqrt

from bloxorz_solver.ui.motion import face_normal

ROW_SKEW, ROW_DROP, COLUMN_RISE, HEIGHT_SCALE = 0.48, 0.62, 0.18, 0.95
CAMERA = (-ROW_SKEW, 1, (ROW_DROP + COLUMN_RISE * ROW_SKEW) / HEIGHT_SCALE)


def project(point, view=(1.0, 0.0, 0.0)):
    col, row, height = point
    scale, left, top = view
    return (left + scale * (col + ROW_SKEW * row),
            top + scale * (ROW_DROP * row - COLUMN_RISE * col - HEIGHT_SCALE * height))


def depth(face):
    return sum(sum(p[i] * CAMERA[i] for i in range(3)) for p in face) / len(face)


def visible(face):
    normal = face_normal(face)
    return sum(normal[i] * CAMERA[i] for i in range(3)) > 1e-8


def shade(color, face):
    normal = face_normal(face)
    length = sqrt(sum(v * v for v in normal))
    if length < 1e-8:
        return tuple(color[:3])
    x, y, z = (v / length for v in normal)
    light = max(0.48, min(1.0, 0.56 + 0.44 * z + 0.16 * y - 0.06 * x))
    return tuple(round(v * light) for v in color[:3])
