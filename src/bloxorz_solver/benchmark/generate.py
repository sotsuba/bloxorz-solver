"""Seeded candidate generation and frozen, stratified corpus construction."""

import argparse
import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from bloxorz_solver.benchmark import VERSION
from bloxorz_solver.benchmark.core import canonical, certify, digest, encode, replay
from bloxorz_solver.game.rules import ROLL_TABLE, occupied_cells
from bloxorz_solver.game.state import NormalBlock, Orientation
from bloxorz_solver.levels.loader import parse_level

FAMILIES = ("ordinary", "fragile", "switch", "split")
TOPOLOGIES = ("walk", "rooms", "random")


@dataclass(frozen=True)
class GenerationConfig:
    family: str = "ordinary"
    topology: str = "walk"
    width: int = 12
    height: int = 9

    def __post_init__(self):
        if self.family not in FAMILIES or self.topology not in TOPOLOGIES:
            raise ValueError("Unknown family or topology")
        if not 9 <= self.width <= 40 or not 7 <= self.height <= 30:
            raise ValueError("Supported dimensions: width 9..40, height 7..30")


def generate(config: GenerationConfig, seed: int) -> dict:
    """Return one candidate in the existing JSON format; certification is separate."""
    rng = random.Random(seed)
    w, h = config.width, config.height
    grid = [["#"] * w for _ in range(h)]
    bridges, switches = [], []
    if config.family in ("switch", "split"):
        cut = w // 2
        left = [(r, c) for r in range(1, h - 1) for c in range(1, cut)]
        right = [(r, c) for r in range(1, h - 1) for c in range(cut + 2, w - 1)]
        for r, c in left + right:
            grid[r][c] = "."
        start, goal = rng.choice(left), rng.choice(right)
        switch_pos = rng.choice([p for p in left if p != start])
        if config.family == "switch":
            row = rng.randrange(1, h - 1)
            bridges = [
                {"id": "gate", "cells": [[row, cut], [row, cut + 1]], "initially_open": False}
            ]
            effect = {"mode": rng.choice(["toggle", "set"]), "targets": ["gate"]}
            if effect["mode"] == "set":
                effect["open"] = True
            switches = [
                {
                    "id": "trigger",
                    "type": rng.choice(["soft", "heavy"]),
                    "position": list(switch_pos),
                    "bridge_effect": effect,
                }
            ]
        else:
            pairs = [
                (a, b) for a in right for b in right if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1
            ]
            a, b = rng.choice(pairs)
            switches = [
                {
                    "id": "split",
                    "type": "split",
                    "position": list(switch_pos),
                    "spawn_positions": [list(a), list(b)],
                }
            ]
        protected = {start, goal, switch_pos}
        for switch in switches:
            protected.update(tuple(p) for p in switch.get("spawn_positions", []))
        # Distinct geometry variants inside the two mechanism-connected islands.
        for r, c in left + right:
            if (r, c) in protected:
                continue
            if config.topology == "random" and rng.random() < 0.12:
                grid[r][c] = "#"
            elif config.topology == "rooms" and r == h // 2 and c % 3 == 0:
                grid[r][c] = "#"
            elif config.topology == "walk" and rng.random() < 0.04:
                grid[r][c] = "#"
    elif config.topology == "walk":
        start = (rng.randrange(1, h - 1), rng.randrange(1, w - 1))
        block = NormalBlock(*start)
        visited = {block}
        standing = {start}
        support = {start}
        endpoints = []
        for _ in range(rng.randrange(30, 100)):
            choices = []
            for dr, dc, orientation in ROLL_TABLE[block.orientation].values():
                nxt = NormalBlock(block.row + dr, block.col + dc, orientation)
                if all(0 < p.row < h - 1 and 0 < p.col < w - 1 for p in occupied_cells(nxt)):
                    choices.append(nxt)
            fresh = [b for b in choices if b not in visited]
            if not choices:
                break
            block = rng.choice(fresh or choices)
            visited.add(block)
            support.update(occupied_cells(block))
            if block.orientation is Orientation.STANDING:
                standing.add((block.row, block.col))
                if (block.row, block.col) != start:
                    endpoints.append((block.row, block.col))
        goal = endpoints[-1] if endpoints else (1, 1)
        if goal == start:
            goal = (h - 2, w - 2)
        for r, c in sorted(support):
            grid[r][c] = "."
        for r in range(1, h - 1):
            for c in range(1, w - 1):
                if rng.random() < 0.08:
                    grid[r][c] = "."
        if config.family == "fragile":
            candidates = sorted(support - standing)
            for r, c in candidates:
                if rng.random() < 0.45:
                    grid[r][c] = "F"
    else:
        for r in range(1, h - 1):
            for c in range(1, w - 1):
                if config.topology == "random":
                    floor = rng.random() > 0.18
                else:
                    floor = c % 5 != 0 or r % 4 in (1, 2)
                grid[r][c] = "." if floor else "#"
        cells = [(r, c) for r in range(1, h - 1) for c in range(1, w - 1) if grid[r][c] == "."]
        start, goal = rng.sample(cells, 2)
        if config.family == "fragile":
            for r, c in cells:
                if rng.random() < 0.2:
                    grid[r][c] = "F"
    grid[start[0]][start[1]] = "S"
    grid[goal[0]][goal[1]] = "G"
    return {
        "id": f"{config.family}-{seed}",
        "name": f"Màn {config.family} {seed}",
        "description": "Màn sinh tự động; xem manifest để biết chứng nhận.",
        "grid": ["".join(row) for row in grid],
        "bridges": bridges,
        "switches": switches,
    }


def candidate_config(family, rng, topology, settings):
    min_w, max_w = settings.get("width_range", [11, 18])
    min_h, max_h = settings.get("height_range", [7, 12])
    return GenerationConfig(family, topology, rng.randint(min_w, max_w), rng.randint(min_h, max_h))


def inspect_candidate(config, seed, limit):
    level = parse_level(generate(config, seed))
    cert = certify(level, limit)
    if cert.status != "solved":
        return None, cert.status
    if not cert.path or not replay(level, cert.path):
        return None, "invalid_path"
    if config.family != "ordinary":
        necessity = certify(level, limit, forbidden=config.family)
        if necessity.status != "exhausted":
            return None, "unnecessary" if necessity.status == "solved" else "necessity_unknown"
    return (level, cert), "accepted"


def build_corpus(settings: dict, output: Path) -> dict:
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    seed = settings.get("seed", 20261019)
    limit = settings.get("max_states", 200_000)
    per_bin = settings.get("per_bin", 30)
    dev_count = settings.get("development_per_bin", 10)
    pilot_size = settings.get("pilot_per_family", 60)
    attempts_per_map = settings.get("attempts_per_map", 200)
    families = settings.get("families", list(FAMILIES))
    if per_bin < 1 or not 0 <= dev_count <= per_bin or pilot_size < 3 or attempts_per_map < 1:
        raise ValueError("Invalid corpus quotas")
    if (
        not families
        or len(set(families)) != len(families)
        or any(f not in FAMILIES for f in families)
    ):
        raise ValueError("families must be a nonempty list of distinct supported families")
    if limit < 1 or settings.get("unsolvable_count", 20) < 0:
        raise ValueError("Invalid state limit or negative fixture count")
    min_w, max_w = settings.get("width_range", [11, 18])
    min_h, max_h = settings.get("height_range", [7, 12])
    if not 9 <= min_w <= max_w <= 40 or not 7 <= min_h <= max_h <= 30:
        raise ValueError("width_range must be within 9..40; height_range within 7..30")
    output.mkdir(parents=True)
    (output / "levels").mkdir()
    manifest = {
        "schema_version": 1,
        "generator_version": VERSION,
        "settings": settings,
        "seed": seed,
        "max_states": limit,
        "bands": {},
        "records": [],
        "generation": {},
        "pilot": {},
        "shortfalls": {},
        "ci_ids": [],
    }
    seen = set()
    for fi, family in enumerate(families):
        rng = random.Random(seed + fi * 1_000_000)
        pilot_depths, pilot_hashes = [], set()
        pilot_reasons = Counter()
        for index in range(pilot_size * attempts_per_map):
            config = candidate_config(family, rng, TOPOLOGIES[index % 3], settings)
            cs = rng.getrandbits(63)
            item, reason = inspect_candidate(config, cs, limit)
            pilot_reasons[reason] += 1
            if item:
                level, cert = item
                identity = canonical(level)
                if identity not in pilot_hashes:
                    pilot_depths.append(len(cert.path))
                    pilot_hashes.add(identity)
            if len(pilot_depths) == pilot_size:
                break
        if len(pilot_depths) < 3:
            raise ValueError(f"Insufficient pilot samples for {family}")
        ordered = sorted(pilot_depths)
        cuts = [ordered[len(ordered) // 3], ordered[2 * len(ordered) // 3]]
        if cuts[0] == cuts[1]:
            raise ValueError(f"Pilot depth bands collapsed for {family}")
        manifest["bands"][family] = cuts
        manifest["pilot"][family] = {"depths": pilot_depths, "reasons": dict(pilot_reasons)}
        seen.update(pilot_hashes)
        # A separate stream ensures pilot sampling cannot consume evaluation seeds.
        rng = random.Random(seed + fi * 1_000_000 + 500_000)
        counts = Counter()
        topology_counts = Counter()
        reasons = Counter()
        for index in range(per_bin * 3 * attempts_per_map):
            topology = TOPOLOGIES[index % 3]
            config = candidate_config(family, rng, topology, settings)
            cs = rng.getrandbits(63)
            item, reason = inspect_candidate(config, cs, limit)
            if item is None:
                reasons[reason] += 1
                continue
            level, cert = item
            depth = len(cert.path)
            band = 0 if depth <= cuts[0] else 1 if depth <= cuts[1] else 2
            if counts[band] >= per_bin:
                reasons["band_full"] += 1
                continue
            topology_quota = per_bin // 3 + (TOPOLOGIES.index(topology) < per_bin % 3)
            if topology_counts[band, topology] >= topology_quota:
                reasons["topology_full"] += 1
                continue
            identity = canonical(level)
            if identity in seen:
                reasons["duplicate"] += 1
                continue
            seen.add(identity)
            data = encode(level)
            filename = f"levels/{level.id}.json"
            (output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            partition = "development" if counts[band] < dev_count else "evaluation"
            manifest["records"].append(
                {
                    "id": level.id,
                    "file": filename,
                    "hash": digest(data),
                    "canonical_hash": identity,
                    "seed": cs,
                    "config": asdict(config),
                    "family": family,
                    "topology": topology,
                    "band": band,
                    "partition": partition,
                    "certificate": asdict(cert),
                    "density": sum(ch != "#" for row in level.grid for ch in row)
                    / (level.width * level.height),
                    "bridges": len(level.bridges),
                    "switches": len(level.switches),
                }
            )
            if counts[band] == 0:
                manifest["ci_ids"].append(level.id)
            counts[band] += 1
            topology_counts[band, topology] += 1
            reasons["accepted"] += 1
            if sum(counts.values()) == per_bin * 3:
                break
        manifest["generation"][family] = dict(reasons)
        manifest["shortfalls"][family] = {str(b): per_bin - counts[b] for b in range(3)}
        print(f"{family}: {sum(counts.values())}/{per_bin * 3}; bands={cuts}", flush=True)
    # Isolated goals give independently obvious negative fixtures with distinct geometry.
    for i in range(settings.get("unsolvable_count", 20)):
        w = 9 + i % 5
        h = 7 + i // 5
        grid = [["#"] * w for _ in range(h)]
        for r in range(1, h - 3):
            for c in range(1, w - 2):
                grid[r][c] = "."
        grid[1][1] = "S"
        grid[h - 2][w - 2] = "G"
        data = {
            "id": f"unsolvable-{i:03}",
            "name": f"Vô nghiệm {i + 1}",
            "grid": ["".join(row) for row in grid],
        }
        level = parse_level(data)
        cert = certify(level, limit)
        if cert.status != "exhausted":
            raise ValueError("Negative fixture could not be certified")
        data = encode(level)
        filename = f"levels/{level.id}.json"
        (output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        manifest["records"].append(
            {
                "id": level.id,
                "file": filename,
                "hash": digest(data),
                "canonical_hash": canonical(level),
                "family": "unsolvable",
                "topology": "isolated",
                "band": None,
                "partition": "negative",
                "certificate": asdict(cert),
            }
        )
    manifest["corpus_hash"] = digest(manifest)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sinh bộ dữ liệu Bloxorz có chứng nhận")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build_corpus(json.loads(args.config.read_text()), args.output)
    return int(any(v for bands in manifest["shortfalls"].values() for v in bands.values()))


if __name__ == "__main__":
    raise SystemExit(main())
