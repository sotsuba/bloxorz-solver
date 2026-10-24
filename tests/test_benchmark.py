"""Certificates, fair measurement, process limits and corpus/report integrity."""

import json
import subprocess
import sys
import tracemalloc
from dataclasses import asdict
from pathlib import Path

import pytest

from bloxorz_solver.benchmark.core import canonical, certify, encode, replay
from bloxorz_solver.benchmark.generate import GenerationConfig, generate, inspect_candidate
from bloxorz_solver.benchmark.measure import measure_search
from bloxorz_solver.benchmark.runner import read_manifest, run_one
from bloxorz_solver.levels.loader import builtin_levels, parse_level
from bloxorz_solver.solvers.astar import AStarSolver
from bloxorz_solver.solvers.bfs import BFSSolver
from bloxorz_solver.solvers.dfs import DFSSolver
from bloxorz_solver.solvers.problem import BloxorzProblem
from bloxorz_solver.solvers.ucs import UCSSolver

CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "v1"


@pytest.mark.parametrize("index", [0, 1, 2, 4])
def test_reference_certificates_match_solvers(index):
    level = builtin_levels()[index]
    reference = certify(level)
    assert reference.status == "solved"
    assert replay(level, reference.path)
    assert not replay(level, reference.path + ["up"])
    problem = BloxorzProblem(level)
    for solver in (BFSSolver(problem), AStarSolver(problem), UCSSolver(problem, cost_mode="unit")):
        result = measure_search(solver, problem.initial_state)
        assert len(result.path) == len(reference.path)
        assert replay(level, result.path)
    assert replay(level, measure_search(DFSSolver(problem), problem.initial_state).path)


def test_unknown_is_not_unsolvable():
    level = builtin_levels()[0]
    assert certify(level, 1).status == "unknown"
    impossible = parse_level({"id": "no", "name": "no", "grid": ["S##G"]})
    assert certify(impossible).status == "exhausted"
    assert certify(impossible).path is None
    with pytest.raises(ValueError):
        certify(level, 0)


@pytest.mark.parametrize("family,index", [("fragile", 1), ("switch", 2), ("split", 4)])
def test_mechanism_necessity(family, index):
    level = builtin_levels()[index]
    assert certify(level).status == "solved"
    assert certify(level, forbidden=family).status == "exhausted"


@pytest.mark.parametrize("family", ["ordinary", "fragile", "switch", "split"])
@pytest.mark.parametrize("topology", ["walk", "rooms", "random"])
def test_seeded_candidates_are_reproducible_and_loadable(family, topology):
    config = GenerationConfig(family, topology)
    first = generate(config, 23)
    assert first == generate(config, 23)
    assert first != generate(config, 24)
    level = parse_level(first)
    assert parse_level(encode(level)) == level


def test_symmetry_identity_and_spawn_order():
    level = builtin_levels()[4]
    data = encode(level)
    data["grid"] = [row[::-1] for row in data["grid"]]
    for switch in data["switches"]:
        switch["position"][1] = level.width - 1 - switch["position"][1]
        for position in switch["spawn_positions"]:
            position[1] = level.width - 1 - position[1]
    assert canonical(parse_level(data)) == canonical(level)
    data["switches"][0]["spawn_positions"].reverse()
    assert canonical(parse_level(data)) != canonical(level)
    padded = encode(level)
    padded["grid"] = ["#" * (level.width + 2)] + ["#" + row + "#" for row in level.grid]
    for switch in padded["switches"]:
        switch["position"] = [v + 1 for v in switch["position"]]
        switch["spawn_positions"] = [[v + 1 for v in p] for p in switch["spawn_positions"]]
    assert canonical(parse_level(padded)) == canonical(level)


@pytest.mark.parametrize("solver_type", [BFSSolver, DFSSolver, UCSSolver, AStarSolver])
def test_adapter_matches_public_solve_without_mutating_solver(solver_type):
    problem = BloxorzProblem(builtin_levels()[0])
    public = solver_type(problem).solve(problem.initial_state)
    timing = measure_search(solver_type(problem), problem.initial_state, mode="timing")
    memory = measure_search(solver_type(problem), problem.initial_state, mode="memory")
    assert public.path == timing.path == memory.path
    assert public.expanded_nodes == timing.expanded_nodes == memory.expanded_nodes
    assert timing.search_time >= 0 and timing.peak_memory is None
    assert memory.search_time is None and memory.peak_memory > 0
    assert not tracemalloc.is_tracing()


def test_adapter_tracing_ownership_and_failure_cleanup():
    problem = BloxorzProblem(builtin_levels()[0])

    class Probe(BFSSolver):
        def _search(self, state):
            assert tracemalloc.is_tracing()
            raise RuntimeError("probe")

    with pytest.raises(RuntimeError, match="probe"):
        measure_search(Probe(problem), problem.initial_state, mode="memory")
    assert not tracemalloc.is_tracing()
    tracemalloc.start()
    try:
        for mode in ("timing", "memory"):
            with pytest.raises(RuntimeError, match="fresh"):
                measure_search(BFSSolver(problem), problem.initial_state, mode=mode)
            assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()


def payload(tmp_path, **overrides):
    level = builtin_levels()[4]
    path = tmp_path / "level.json"
    path.write_text(json.dumps(encode(level)))
    return {
        "level": str(path),
        "solver": "bfs",
        "mode": "timing",
        "timeout": 10,
        "memory_mib": 1024,
        "reference": asdict(certify(level)),
        **overrides,
    }


def test_worker_timeout_and_success(tmp_path):
    data = payload(tmp_path)
    result = run_one(data)
    assert result["status"] == "solved"
    assert result["peak_memory"] is None
    assert result["loading_time"] >= 0
    assert run_one({**data, "timeout": 0.00001})["status"] == "timeout"
    assert run_one({**data, "mode": "memory"})["search_time"] is None


def test_worker_memory_failure_is_labelled(tmp_path):
    data = payload(tmp_path, memory_mib=64)
    code = """
import json, sys
from bloxorz_solver.solvers.bfs import BFSSolver
from bloxorz_solver.benchmark.runner import worker
def fail(self, state):
    allocation = bytearray(128 * 1024 * 1024)
    return None, len(allocation)
BFSSolver._search = fail
print(json.dumps(worker(json.load(sys.stdin))))
"""
    child = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(data),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(child.stdout)["status"] == "memory_limit"


def test_worker_outer_timeout_is_labelled(monkeypatch, tmp_path):
    def expired(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", expired)
    assert run_one(payload(tmp_path))["status"] == "timeout"


def test_frozen_corpus_quotas_disjointness_and_regeneration():
    manifest = read_manifest(CORPUS)
    records = manifest["records"]
    assert len(records) == 380
    assert len(manifest["ci_ids"]) == 12
    assert not any(n for bands in manifest["shortfalls"].values() for n in bands.values())
    dev = {r["canonical_hash"] for r in records if r["partition"] == "development"}
    evaluation = {r["canonical_hash"] for r in records if r["partition"] == "evaluation"}
    assert len(dev) == 120 and len(evaluation) == 240
    assert dev.isdisjoint(evaluation)
    for family in ("ordinary", "fragile", "switch", "split"):
        record = next(r for r in records if r["family"] == family)
        item, reason = inspect_candidate(
            GenerationConfig(**record["config"]), record["seed"], manifest["max_states"]
        )
        assert reason == "accepted"
        level, certificate = item
        assert encode(level) == json.loads((CORPUS / record["file"]).read_text())
        assert asdict(certificate) == record["certificate"]


def test_report_aggregation_keeps_failures_out_of_successes():
    pytest.importorskip("matplotlib")
    from bloxorz_solver.benchmark.report import summarize

    records = [
        {"id": "a", "certificate": {"status": "solved"}},
        {"id": "b", "certificate": {"status": "solved"}},
    ]
    rows = [
        {
            "id": "a",
            "solver": s,
            "mode": "timing",
            "status": "solved",
            "search_time": 1,
            "expanded_nodes": 3,
            "length_ratio": 1,
        }
        for s in ("bfs", "dfs")
    ]
    rows += [
        {"id": "b", "solver": s, "mode": "timing", "status": "timeout"} for s in ("bfs", "dfs")
    ]
    positive, _, solved, common, values, memory = summarize(rows, records, ["bfs", "dfs"])
    assert len(positive) == 2
    assert common == {"a"} and solved["bfs"] == {"a"}
    assert ("bfs", "b") not in values
    assert not memory


def test_ci_subset_reference_paths_and_solver_optimality():
    manifest = read_manifest(CORPUS)
    for record in manifest["records"]:
        if record["id"] not in manifest["ci_ids"]:
            continue
        level = parse_level(json.loads((CORPUS / record["file"]).read_text()))
        problem = BloxorzProblem(level)
        for solver in (
            BFSSolver(problem),
            UCSSolver(problem, cost_mode="unit"),
            AStarSolver(problem),
        ):
            measurement = measure_search(solver, problem.initial_state)
            assert replay(level, measurement.path)
            assert len(measurement.path) == len(record["certificate"]["path"])


def test_incomplete_report_is_rejected(tmp_path):
    pytest.importorskip("matplotlib")
    from bloxorz_solver.benchmark.report import create_report

    manifest = read_manifest(CORPUS)
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "corpus_hash": manifest["corpus_hash"],
                "selected_ids": [manifest["records"][0]["id"]],
                "solvers": ["bfs"],
                "repeats": 1,
            }
        )
    )
    (tmp_path / "runs.jsonl").write_text("")
    with pytest.raises(ValueError, match="Incomplete"):
        create_report(CORPUS, tmp_path, tmp_path / "report")


def test_report_renders_when_every_solver_hits_a_limit(tmp_path):
    pytest.importorskip("matplotlib")
    from bloxorz_solver.benchmark.report import create_report

    manifest = read_manifest(CORPUS)
    identity = manifest["records"][0]["id"]
    metadata = {
        "corpus_hash": manifest["corpus_hash"],
        "selected_ids": [identity],
        "solvers": ["bfs", "dfs", "ucs", "astar"],
        "repeats": 1,
        "timeout": 10,
        "memory_mib": 1024,
        "partition": "evaluation",
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    rows = [
        {
            "id": identity,
            "solver": solver,
            "mode": mode,
            "repetition": 0,
            "status": "timeout" if mode == "timing" else "memory_limit",
            "family": "ordinary",
        }
        for solver in metadata["solvers"]
        for mode in ("timing", "memory")
    ]
    (tmp_path / "runs.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    output = tmp_path / "report"
    create_report(CORPUS, tmp_path, output)
    assert len(list(output.glob("*.svg"))) == 10
    assert len(list(output.glob("*.png"))) == 10
    report = (output / "bao-cao.md").read_text()
    assert "| BFS | 0/1 | Không có dữ liệu |" in report
    assert "Vượt bộ nhớ" in report
