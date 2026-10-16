"""Strict JSON parsing for external and packaged Bloxorz levels."""

import json
from importlib.resources import files
from pathlib import Path

from bloxorz_solver.game.state import (
    Bridge,
    BridgeEffect,
    EffectMode,
    Level,
    Position,
    Switch,
    SwitchKind,
)
from bloxorz_solver.game.validation import validate_level


class LevelFormatError(ValueError):
    """A level cannot be interpreted as a valid game board."""


def load_level(path: str | Path) -> Level:
    """Load a UTF-8 JSON stage and include its filename in error messages."""
    path = Path(path)
    try:
        return parse_level(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LevelFormatError(f"{path.name}: {exc}") from exc


def builtin_levels() -> tuple[Level, ...]:
    """Read bundled stage resources even when the package is installed elsewhere."""
    resources = files("bloxorz_solver").joinpath("levels")
    return tuple(
        parse_level(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(resources.iterdir(), key=lambda p: p.name)
        if path.name.endswith(".json")
    )


def parse_level(data: object) -> Level:
    """Validate input types and construct an immutable static level."""
    try:
        return _parse_level(_object(data, "level"))
    except (KeyError, TypeError, ValueError) as exc:
        raise LevelFormatError(str(exc)) from exc


def _parse_level(data: dict) -> Level:
    """Parse terrain first so marker positions are derived rather than duplicated."""
    grid = tuple(_text(row, "grid row") for row in _array(data.get("grid"), "grid"))
    start = _find_marker(grid, "S")
    goal = _find_marker(grid, "G")
    level = Level(
        id=_text(data.get("id"), "id"),
        name=_text(data.get("name"), "name"),
        grid=grid,
        start=start,
        goal=goal,
        bridges=tuple(_bridge(item) for item in _array(data.get("bridges", []), "bridges")),
        switches=tuple(_switch(item) for item in _array(data.get("switches", []), "switches")),
        description=_text(data.get("description", ""), "description", allow_empty=True),
    )
    validate_level(level)
    return level


def _find_marker(grid: tuple[str, ...], marker: str) -> Position:
    """Require a single start or goal and derive its coordinate."""
    positions = [
        Position(r, c) for r, row in enumerate(grid) for c, tile in enumerate(row) if tile == marker
    ]
    if len(positions) != 1:
        raise ValueError(f"grid must contain exactly one {marker}")
    return positions[0]


def _bridge(value: object) -> Bridge:
    """Parse bridge cells and their initial passability."""
    data = _object(value, "bridge")
    opened = data.get("initially_open", False)
    if not isinstance(opened, bool):
        raise ValueError("initially_open must be a Boolean")
    return Bridge(
        _text(data.get("id"), "bridge id"),
        tuple(_position(pos) for pos in _array(data.get("cells"), "bridge cells")),
        opened,
    )


def _switch(value: object) -> Switch:
    """Parse one switch, preserving optional split bridge effects."""
    data = _object(value, "switch")
    return Switch(
        id=_text(data.get("id"), "switch id"),
        position=_position(data.get("position")),
        kind=SwitchKind(_text(data.get("type"), "switch type")),
        bridge_effect=_effect(data["bridge_effect"]) if "bridge_effect" in data else None,
        spawn_positions=tuple(
            _position(pos) for pos in _array(data.get("spawn_positions", []), "spawn_positions")
        ),
    )


def _effect(value: object) -> BridgeEffect:
    """Parse toggle or set behavior; validation checks its references."""
    data = _object(value, "bridge_effect")
    return BridgeEffect(
        EffectMode(_text(data.get("mode"), "effect mode")),
        tuple(_text(target, "bridge target") for target in _array(data.get("targets"), "targets")),
        data.get("open"),
    )


def _position(value: object) -> Position:
    """Reject noninteger coordinates, including Booleans disguised as integers."""
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(part) is not int for part in value)
    ):
        raise ValueError("position must be an array of two integer coordinates")
    return Position(*value)


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{label} must be a {'nonempty ' if not allow_empty else ''}string")
    return value
