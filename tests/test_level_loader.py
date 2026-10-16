"""Level format validation and file loading."""

import json

import pytest

from bloxorz_solver.levels.loader import (
    LevelFormatError,
    load_level,
    parse_level,
)


def minimal_data():
    return {"id": "simple", "name": "Simple", "grid": ["S..G"]}


@pytest.mark.parametrize(
    "grid",
    [[], [""], ["S.G", ".."], ["S?G"], ["...G"], ["SS.G"], ["S..."], [7]],
)
def test_invalid_grid_is_rejected(grid):
    with pytest.raises(LevelFormatError):
        parse_level({**minimal_data(), "grid": grid})


@pytest.mark.parametrize("value", [None, [], 5, "level"])
def test_top_level_must_be_object(value):
    with pytest.raises(LevelFormatError, match="object"):
        parse_level(value)


def test_minimal_valid_level():
    level = parse_level(minimal_data())
    assert level.start == (0, 0)
    assert level.goal == (0, 3)
    assert (level.width, level.height) == (4, 1)


@pytest.mark.parametrize("position", [[True, 1], [0], [0, 1, 2], [0, "1"], [-1, 1], [9, 1]])
def test_invalid_switch_position(position):
    data = {
        **minimal_data(),
        "switches": [
            {"id": "s", "type": "split", "position": position, "spawn_positions": [[0, 1], [0, 2]]}
        ],
    }
    with pytest.raises(LevelFormatError):
        parse_level(data)


def test_bridge_must_cover_void():
    with pytest.raises(LevelFormatError, match="void"):
        parse_level({**minimal_data(), "bridges": [{"id": "b", "cells": [[0, 1]]}]})


def mechanism_data():
    return {
        "id": "mechanisms",
        "name": "Mechanisms",
        "grid": ["S..#G"],
        "bridges": [{"id": "b", "cells": [[0, 3]]}],
        "switches": [
            {
                "id": "s",
                "type": "soft",
                "position": [0, 1],
                "bridge_effect": {"mode": "toggle", "targets": ["b"]},
            }
        ],
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["bridges"].append(d["bridges"][0].copy()),
        lambda d: d["bridges"].append({"id": "b2", "cells": [[0, 3]]}),
        lambda d: d["switches"].append({**d["switches"][0], "id": "s2"}),
        lambda d: d["switches"][0]["bridge_effect"].update(targets=["missing"]),
        lambda d: d["switches"][0]["bridge_effect"].update(mode="set"),
        lambda d: d["switches"][0]["bridge_effect"].update(mode="set", open=1),
        lambda d: d["switches"][0]["bridge_effect"].update(targets=["b", "b"]),
        lambda d: d["switches"][0].update(type="unknown"),
        lambda d: d["switches"][0].update(position=[0, 4]),
        lambda d: d["bridges"][0].update(initially_open="false"),
        lambda d: d["bridges"][0].update(cells=[]),
        lambda d: d.update(switches="bad"),
    ],
)
def test_malformed_mechanisms_are_rejected(mutate):
    data = mechanism_data()
    mutate(data)
    with pytest.raises(LevelFormatError):
        parse_level(data)


@pytest.mark.parametrize("spawns", [[[0, 1]], [[0, 1], [0, 1]], [[0, 1], [8, 8]], [[0, 1], [0, 3]]])
def test_split_spawn_validation(spawns):
    data = {
        "id": "split",
        "name": "Split",
        "grid": ["S..#G"],
        "switches": [{"id": "s", "type": "split", "position": [0, 2], "spawn_positions": spawns}],
    }
    with pytest.raises(LevelFormatError):
        parse_level(data)


def test_parse_error_has_filename_and_line(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"grid": [}', encoding="utf-8")
    with pytest.raises(LevelFormatError, match=r"broken.json.*line"):
        load_level(path)


def test_unsolvable_level_is_still_loadable():
    level = parse_level({"id": "no_path", "name": "No path", "grid": ["S#G"]})
    assert level.goal == (0, 2)


def test_loading_json_file(tmp_path):
    path = tmp_path / "level.json"
    path.write_text(json.dumps(minimal_data()), encoding="utf-8")
    assert load_level(path).id == "simple"
