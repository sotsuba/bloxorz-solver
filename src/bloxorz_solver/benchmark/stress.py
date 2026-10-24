"""Mechanism-rich v2 candidates with engine-replayed construction witnesses."""

import random
import time
from collections import deque

from bloxorz_solver.benchmark.core import canonical, digest, encode, replay
from bloxorz_solver.game.rules import initial_state, is_goal, occupied_cells, safe_transitions
from bloxorz_solver.game.state import EventType, NormalBlock, Orientation, SplitBlock
from bloxorz_solver.levels.loader import parse_level

FAMILIES = ("dependency", "shared", "split_bridge")


def route(level, start, predicate, allowed, limit=30_000):
    queue, parents = deque([start]), {start: None}
    while queue:
        state = queue.popleft()
        if predicate(state):
            path, cursor = [], state
            while parents[cursor] is not None:
                cursor, action = parents[cursor]
                path.append(action)
            return state, path[::-1]
        for action, result in safe_transitions(level, state):
            nxt = result.next_state
            if nxt not in parents and allowed(nxt):
                if len(parents) >= limit:
                    raise ValueError("Local witness search exceeded its state budget")
                parents[nxt] = state, action.value
                queue.append(nxt)
    raise ValueError("Modules have no valid connecting witness")


def generate_candidate(family: str, tier: int, seed: int):
    if family not in FAMILIES or tier not in (0, 1, 2):
        raise ValueError("Invalid stress family/tier")
    rng = random.Random(seed)
    n = (2, 4, 6)[tier]
    w = rng.randint(max(6 * n + 3, (16, 24, 32)[tier]), (24, 32, 40)[tier])
    h = rng.randint((12, 16, 20)[tier], (18, 24, 30)[tier])
    split = family == "split_bridge"
    top = 5 if split else 1
    center = (top + h - 2) // 2
    grid = [["#"] * w for _ in range(h)]
    for r in range(top, h - 1):
        for c in range(1, w - 1):
            if not any(c in (5 + 6 * i, 6 + 6 * i) for i in range(n)):
                grid[r][c] = "."
    bridges, switches, exits = [], [], []
    for i in range(n):
        row = rng.randrange(top + 1, h - 2)
        exits.append((row, 7 + 6 * i))
        bridges.append(
            {
                "id": f"b{i:02}",
                "cells": [[row, 5 + 6 * i], [row, 6 + 6 * i]],
                "initially_open": family == "shared" and i % 3 == 1,
            }
        )
        sr = rng.choice([r for r in range(top, h - 1) if abs(r - row) >= 2])
        sc = 1 + 6 * i + rng.randrange(4)
        targets = [f"b{i:02}"]
        mode = rng.choice(["set", "toggle"])
        if family == "shared":
            targets += [f"b{j:02}" for j in (i - 1, i + 1) if 0 <= j < n]
            mode = "toggle" if i % 2 == 0 else "set"
        effect = {"mode": mode, "targets": targets}
        if mode == "set":
            effect["open"] = True
        switches.append(
            {
                "id": f"s{i:02}",
                "type": rng.choice(["soft", "heavy"]),
                "position": [sr, sc],
                "bridge_effect": effect,
            }
        )
    start, goal = (center, 1), exits[-1]
    if split:
        for r in range(1, 4):
            for c in range(1, 5):
                grid[r][c] = "."
        start = (2, 1)
        switches.append(
            {
                "id": "split_start",
                "type": "split",
                "position": [2, 4],
                "spawn_positions": [[center, 1], [center + 2, 3]],
            }
        )
        if tier == 2:
            for r in range(1, 4):
                for c in range(w - 6, w - 1):
                    grid[r][c] = "."
            goal = (2, w - 2)
            switches.append(
                {
                    "id": "split_finish",
                    "type": "split",
                    "position": [top, w - 2],
                    "spawn_positions": [[1, w - 6], [3, w - 4]],
                }
            )
    protected = {start, goal, *exits}
    for switch in switches:
        protected.add(tuple(switch["position"]))
        protected.update(tuple(p) for p in switch.get("spawn_positions", []))
    # Terrain variation is certified by local search, never presumed solvable.
    for r in range(top, h - 1):
        for c in range(1, w - 1):
            if grid[r][c] == "." and (r, c) not in protected:
                value = rng.random()
                if value < 0.035:
                    grid[r][c] = "#"
                elif value < 0.07:
                    grid[r][c] = "F"
    grid[start[0]][start[1]], grid[goal[0]][goal[1]] = "S", "G"
    data = {
        "id": f"v2-{family}-{tier}-{seed}",
        "name": f"Cơ chế {family} · mức {tier + 1}",
        "grid": ["".join(row) for row in grid],
        "bridges": bridges,
        "switches": switches,
    }
    level = parse_level(data)
    state, witness = initial_state(level), []
    if split:
        state, part = route(level, state, lambda s: isinstance(s.block, SplitBlock), lambda s: True)
        witness += part
    for i, target in enumerate(exits):

        def reached(s, target=target):
            return s.block == NormalBlock(*target, Orientation.STANDING)

        def allowed(s, i=i):
            return all(
                top <= p.row < h - 1 and 1 + 6 * i <= p.col <= 7 + 6 * i
                for p in occupied_cells(s.block)
            )

        state, part = route(level, state, reached, allowed)
        witness += part
    if not is_goal(level, state):
        state, part = route(level, state, lambda s: is_goal(level, s), lambda s: True)
        witness += part
    if not replay(level, witness):
        raise ValueError("Construction witness failed replay")
    return level, witness


def oracle(
    level,
    *,
    max_states=1_000_000,
    seconds=30,
    witness=None,
    forbidden_bridge=None,
    forbidden_split=False,
    enumerate_graph=False,
):
    """Unit BFS: optimality survives an unfinished, separately bounded enumeration."""
    start = initial_state(level)
    queue, parents, depths = deque([start]), {start: None}, {start: 0}
    started = time.monotonic()
    lower, path, masks, edges, cutoff = 0, None, {start.bridge_mask}, 0, None
    while queue:
        if len(parents) >= max_states or time.monotonic() - started >= seconds:
            cutoff = "state_limit" if len(parents) >= max_states else "timeout"
            break
        state = queue.popleft()
        depth = depths[state]
        # All shallower layers have been checked for a goal.
        lower = depth
        if is_goal(level, state):
            if path is None:
                cursor, path = state, []
                while parents[cursor] is not None:
                    cursor, action = parents[cursor]
                    path.append(action)
                path.reverse()
            if not enumerate_graph:
                break
            continue
        for action, result in safe_transitions(level, state):
            if forbidden_split and any(e.kind is EventType.BLOCK_SPLIT for e in result.events):
                continue
            if forbidden_bridge and any(
                level.bridge_at.get(p) == forbidden_bridge
                for p in occupied_cells(result.next_state.block)
            ):
                continue
            edges += 1
            nxt = result.next_state
            if nxt not in parents:
                if len(parents) >= max_states:
                    cutoff = "state_limit"
                    break
                parents[nxt], depths[nxt] = (state, action.value), depth + 1
                masks.add(nxt.bridge_mask)
                queue.append(nxt)
        if cutoff:
            break
    complete = not queue and cutoff is None and (path is None or enumerate_graph)
    if path is not None:
        status, lower = "optimal", len(path)
    elif complete:
        status = "exhausted"
    else:
        status = "witness" if witness is not None else "unknown"
    best_path = path if path is not None else witness
    return {
        "status": status,
        "path": best_path,
        "optimal_length": len(path) if path else None,
        "lower_bound": lower,
        "upper_bound": len(best_path) if best_path else None,
        "discovered_states": len(parents),
        "edges_observed": edges,
        "bridge_masks_observed": len(masks),
        "graph_complete": complete,
        "cutoff": cutoff,
        "elapsed_seconds": time.monotonic() - started,
    }


def evaluate_candidate(job):
    """One disposable process; its parent enforces a wall deadline and AS limit."""
    level, witness = generate_candidate(job["family"], job["tier"], job["seed"])
    reference = oracle(level, max_states=job["max_states"], seconds=job["seconds"], witness=witness)
    reference.pop("elapsed_seconds", None)
    necessity = {}
    for bridge in level.bridges[:2]:
        necessity[bridge.id] = oracle(
            level, max_states=job["max_states"], seconds=job["seconds"], forbidden_bridge=bridge.id
        )["status"]
    if job["family"] == "split_bridge":
        necessity["split"] = oracle(
            level, max_states=job["max_states"], seconds=job["seconds"], forbidden_split=True
        )["status"]
    certified = reference["status"] == "optimal" and all(
        v == "exhausted" for v in necessity.values()
    )
    return {
        "data": encode(level),
        "hash": digest(encode(level)),
        "canonical_hash": canonical(level),
        "certificate": reference,
        "witness": witness,
        "necessity": necessity,
        "cohort": "standard" if certified else "challenge",
    }
