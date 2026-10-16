"""Shared deterministic game fixtures."""

import json
import os
from pathlib import Path

import pytest

from bloxorz.domain.models import Level, Position
from bloxorz.domain.validation import validate_level

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def stage_routes():
    """Load fixed winning action sequences without adding a solver to the game."""
    path = Path(__file__).parent / "fixtures" / "stage_routes.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def make_level():
    """Build a floor board with optional terrain and mechanisms."""

    def create(*, grid=None, start=(4, 4), goal=(8, 8), bridges=(), switches=()):
        if grid is None:
            cells = [list("..........") for _ in range(10)]
            cells[start[0]][start[1]] = "S"
            cells[goal[0]][goal[1]] = "G"
            for bridge in bridges:
                for cell in bridge.cells:
                    cells[cell.row][cell.col] = "#"
            grid = tuple("".join(row) for row in cells)
        level = Level(
            id="test",
            name="Test board",
            grid=tuple(grid),
            start=Position(*start),
            goal=Position(*goal),
            bridges=tuple(bridges),
            switches=tuple(switches),
        )
        validate_level(level)
        return level

    return create
