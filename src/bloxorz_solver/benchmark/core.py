"""Independent bounded graph oracle, portable level serialization and identities."""

import hashlib
import json
from collections import deque
from dataclasses import asdict, dataclass

from bloxorz_solver.game.rules import (
    initial_state,
    is_goal,
    occupied_cells,
    safe_transitions,
    transition,
)
from bloxorz_solver.game.state import Action, EventType, Level, Outcome
from bloxorz_solver.levels.loader import parse_level


def encode(level: Level) -> dict:
    data = asdict(level)
    data.pop("start")
    data.pop("goal")
    for switch in data["switches"]:
        switch["type"] = switch.pop("kind")
        if switch["bridge_effect"] is None:
            del switch["bridge_effect"]
    return json.loads(json.dumps(data))


def digest(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def canonical(level: Level) -> str:
    """D4 identity, ignoring padding/labels, preserving IDs and spawn ordering.

    Mechanism IDs are retained because their lexical order affects simultaneous effects.
    """
    source = encode(level)
    points = [(r, c) for r, row in enumerate(level.grid) for c, ch in enumerate(row) if ch != "#"]
    points += [tuple(p) for b in source["bridges"] for p in b["cells"]]
    variants = []
    for swap in (False, True):
        for sr, sc in ((1, 1), (1, -1), (-1, 1), (-1, -1)):

            def raw(p, sr=sr, sc=sc, swap=swap):
                r, c = p
                return (sr * c, sc * r) if swap else (sr * r, sc * c)

            moved = [raw(p) for p in points]
            mr, mc = min(p[0] for p in moved), min(p[1] for p in moved)

            def pos(p, raw=raw, mr=mr, mc=mc):
                r, c = raw(p)
                return [r - mr, c - mc]

            h = max(p[0] for p in moved) - mr + 1
            w = max(p[1] for p in moved) - mc + 1
            grid = [["#"] * w for _ in range(h)]
            for r, row in enumerate(level.grid):
                for c, ch in enumerate(row):
                    if ch != "#":
                        nr, nc = pos((r, c))
                        grid[nr][nc] = ch
            data = json.loads(json.dumps(source))
            data["grid"] = ["".join(row) for row in grid]
            for key in ("id", "name", "description"):
                data.pop(key, None)
            for bridge in data["bridges"]:
                bridge["cells"] = sorted(pos(p) for p in bridge["cells"])
            for switch in data["switches"]:
                switch["position"] = pos(switch["position"])
                switch["spawn_positions"] = [pos(p) for p in switch["spawn_positions"]]
            data["bridges"].sort(key=lambda b: b["id"])
            data["switches"].sort(key=lambda s: s["id"])
            variants.append(json.dumps(data, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256(min(variants).encode()).hexdigest()


@dataclass
class Certificate:
    status: str
    path: list[str] | None
    reachable_states: int
    edges: int
    branching: float


def certify(level: Level, max_states: int = 200_000, *, forbidden: str = "") -> Certificate:
    """Enumerate all reachable states; BFS first goal gives an exact unit distance.

    Goals are terminal, matching the engine. No compared solver is used here.
    """
    if max_states < 1:
        raise ValueError("max_states must be positive")
    start = initial_state(level)
    queue = deque([start])
    parents = {start: None}
    path = None
    edges = expanded = 0
    while queue:
        state = queue.popleft()
        if is_goal(level, state):
            if path is None:
                path = []
                cursor = state
                while parents[cursor] is not None:
                    cursor, action = parents[cursor]
                    path.append(action)
                path.reverse()
            continue
        expanded += 1
        for action, result in safe_transitions(level, state):
            if forbidden == "switch" and any(
                e.kind is EventType.SWITCH_TRIGGERED for e in result.events
            ):
                continue
            if forbidden == "split" and any(e.kind is EventType.BLOCK_SPLIT for e in result.events):
                continue
            if forbidden == "fragile" and any(
                level.grid[p.row][p.col] == "F" for p in occupied_cells(result.next_state.block)
            ):
                continue
            edges += 1
            successor = result.next_state
            if successor in parents:
                continue
            if len(parents) >= max_states:
                return Certificate("unknown", None, len(parents), edges, edges / expanded)
            parents[successor] = (state, action.value)
            queue.append(successor)
    return Certificate(
        "solved" if path is not None else "exhausted",
        path,
        len(parents),
        edges,
        edges / max(1, expanded),
    )


def replay(level: Level, path: list[str]) -> bool:
    state = initial_state(level)
    try:
        for action in path:
            result = transition(level, state, Action(action))
            if result.outcome not in (Outcome.MOVED, Outcome.WON):
                return False
            state = result.next_state
    except (ValueError, TypeError):
        return False
    return is_goal(level, state)


def validate_payload(data: dict) -> Level:
    return parse_level(data)
