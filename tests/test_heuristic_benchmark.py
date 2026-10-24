"""Integration coverage for heuristic factories, measurement, and experiment identities."""

import json
import shutil
import tracemalloc
from dataclasses import asdict
from pathlib import Path

import pytest

from bloxorz_solver.benchmark.core import certify, digest, encode
from bloxorz_solver.benchmark.experiments import experiments, report_view
from bloxorz_solver.benchmark.measure import measure_solver
from bloxorz_solver.benchmark.runner import read_manifest, run_benchmark, run_one
from bloxorz_solver.levels.loader import builtin_levels
from bloxorz_solver.solvers.heuristics import HEURISTICS

CORPUS = Path(__file__).resolve().parents[1] / "benchmarks/v1"


def small_corpus(path):
    manifest = read_manifest(CORPUS)
    record = next(r for r in manifest["records"] if r["partition"] == "development")
    manifest["records"] = [record]
    manifest["ci_ids"] = [record["id"]]
    manifest.pop("corpus_hash")
    manifest["corpus_hash"] = digest(manifest)
    (path / record["file"]).parent.mkdir(parents=True)
    shutil.copyfile(CORPUS / record["file"], path / record["file"])
    (path / "manifest.json").write_text(json.dumps(manifest))
    return manifest


@pytest.fixture
def worker_payload(tmp_path):
    level = builtin_levels()[0]
    path = tmp_path / "level.json"
    path.write_text(json.dumps(encode(level)))
    return dict(
        level=str(path),
        solver="astar",
        mode="timing",
        timeout=5,
        memory_mib=1024,
        reference=asdict(certify(level)),
    )


def test_all_factories_run_in_real_workers(worker_payload):
    for name in [*HEURISTICS, "bloxorz_solver.solvers.heuristics:zero"]:
        result = run_one({**worker_payload, "heuristic": name})
        assert result["status"] == "solved", result
        assert result["initialization_time"] >= 0
        assert result["total_time"] == pytest.approx(
            result["initialization_time"] + result["search_time"]
        )
        assert result["length_ratio"] == 1
    memory = run_one({**worker_payload, "heuristic": "relaxed_board", "mode": "memory"})
    assert memory["peak_memory"] > 0
    assert memory["search_time"] is memory["total_time"] is memory["initialization_time"] is None


def test_custom_factory_errors_and_initialization_timeout(worker_payload, tmp_path, monkeypatch):
    module = tmp_path / "experiment_plugins.py"
    module.write_text("""
import time
def slow(problem):
    time.sleep(1)
    return lambda state: 0
def broken(problem):
    raise RuntimeError("factory failed")
def invalid(problem):
    return 42
def negative(problem):
    return lambda state: -1
def table(problem):
    data = bytearray(2 * 1024 * 1024)
    return lambda state: data[0]
""")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    assert (
        run_one({**worker_payload, "heuristic": "experiment_plugins:slow", "timeout": 0.05})[
            "status"
        ]
        == "timeout"
    )
    for name in ("broken", "invalid", "negative"):
        result = run_one({**worker_payload, "heuristic": f"experiment_plugins:{name}"})
        assert result["status"] == "error" and result["error"]
    memory = run_one({**worker_payload, "heuristic": "experiment_plugins:table", "mode": "memory"})
    assert memory["status"] == "solved"
    assert memory["peak_memory"] >= 2 * 1024 * 1024


@pytest.mark.parametrize("mode", ["timing", "memory"])
def test_factory_measurement_cleans_up_on_construction_failure(mode):
    def fail():
        raise ValueError("construction failed")

    with pytest.raises(ValueError, match="construction failed"):
        measure_solver(fail, None, mode=mode)
    assert not tracemalloc.is_tracing()
    tracemalloc.start()
    try:
        with pytest.raises(RuntimeError, match="fresh"):
            measure_solver(fail, None, mode=mode)
        assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()


def test_experiment_definitions_and_legacy_reporting():
    variants = experiments(["bfs", "astar"], list(HEURISTICS))
    assert len(variants) == 5
    assert len({v["id"] for v in variants}) == 5
    assert all(v["source_hash"] for v in variants if v["solver"] == "astar")
    old, rows, labels = report_view({"solvers": ["astar"]}, [{"solver": "astar"}])
    assert old["solvers"] == ["astar"] and labels["astar"] == "A* / Manhattan"
    assert rows[0]["solver"] == "astar"
    with pytest.raises(ValueError, match="distinct heuristics"):
        experiments(["astar"], ["zero", "zero"])


def test_run_matrix_and_reports_keep_variants_separate(tmp_path, monkeypatch):
    corpus, output = tmp_path / "corpus", tmp_path / "results"
    manifest = small_corpus(corpus)
    path = manifest["records"][0]["certificate"]["path"]

    def fake_worker(payload):
        memory = payload["mode"] == "memory"
        return dict(
            status="solved",
            path=path,
            solution_length=len(path),
            length_ratio=1,
            search_time=None if memory else 0.02,
            initialization_time=None if memory else 0.01,
            total_time=None if memory else 0.03,
            expanded_nodes=10,
            peak_memory=1000 if memory else None,
        )

    monkeypatch.setattr("bloxorz_solver.benchmark.runner.run_one", fake_worker)
    rows = run_benchmark(
        corpus,
        output,
        partition="development",
        repeats=2,
        solvers=["bfs", "astar"],
        heuristics=list(HEURISTICS),
    )
    assert len(rows) == 15
    assert len({r["experiment"] for r in rows}) == 5
    assert {r["solver"] for r in rows} == {"bfs", "astar"}
    metadata = json.loads((output / "metadata.json").read_text())
    _, viewed, _ = report_view(metadata, rows)
    assert len({r["solver"] for r in viewed}) == 5

    pytest.importorskip("matplotlib")
    from bloxorz_solver.benchmark.paper import aggregate, load_data
    from bloxorz_solver.benchmark.report import create_report

    _, meta, records, loaded = load_data(corpus, output)
    samples, common = aggregate(records, loaded, meta["solvers"], 2)
    assert len(samples) == 5 and len(common) == 1
    assert all(sample["total_time"] == 0.03 for sample in samples.values())
    report = tmp_path / "report"
    create_report(corpus, output, report)
    text = (report / "bao-cao.md").read_text()
    for label in ("Zero", "Manhattan", "Euclidean", "Relaxed board"):
        assert f"A* / {label}" in text
    assert "30.000" in text
    # Removing one variant's repetition must invalidate the experiment.
    (output / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows[:-1]))
    with pytest.raises(ValueError, match="Incomplete"):
        create_report(corpus, output, report)


def test_pipeline_resume_uses_heuristic_definitions(tmp_path, monkeypatch):
    from bloxorz_solver.benchmark import pipeline as module

    output = tmp_path / "pipeline"
    manifest = small_corpus(output / "corpus")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "heuristics": ["zero", "relaxed_board"],
                "search_seconds": 0.01,
                "generation_seconds": 1,
                "measurement_seconds": 30,
                "figure_seconds": 1,
                "total_seconds": 32,
                "repeats": 1,
            }
        )
    )
    settings = module.validate_settings(json.loads(config.read_text()))
    variants = experiments(module.SOLVERS, settings["heuristics"])
    fingerprint = digest({"source": module.source_hash(), "experiments": variants})
    checkpoint = {
        "config_hash": digest(settings),
        "source_hash": fingerprint,
        "corpus_frozen": True,
        "corpus_hash": manifest["corpus_hash"],
        "invocations": [],
    }
    module.write_json(output / "checkpoint.json", checkpoint)
    # Select one evaluation record so the pipeline schedules its experiment matrix.
    record = manifest["records"][0]
    record["partition"] = "evaluation"
    record["tier"], record["cohort"] = 0, "standard"
    manifest.pop("corpus_hash")
    manifest["corpus_hash"] = digest(manifest)
    module.write_json(output / "corpus/manifest.json", manifest)
    checkpoint["corpus_hash"] = manifest["corpus_hash"]
    module.write_json(output / "checkpoint.json", checkpoint)
    calls = []

    def fake(payload):
        calls.append(payload)
        return {"status": "timeout"}

    monkeypatch.setattr(module, "hardware_limits", lambda *_: {"workers": 1})
    monkeypatch.setattr(module, "environment", lambda: {})
    monkeypatch.setattr(module, "run_one", fake)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: type("Completed", (), dict(returncode=0, stdout="", stderr=""))(),
    )
    module.pipeline(config, output, resume=True)
    assert len(calls) == 10  # BFS, DFS, UCS, and two A* variants; timing + memory.
    assert {c["heuristic"] for c in calls if c["solver"] == "astar"} == {"zero", "relaxed_board"}
    calls.clear()
    module.pipeline(config, output, resume=True)
    assert not calls
    changed = json.loads(config.read_text()) | {"heuristics": ["manhattan"]}
    config.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="Resume rejected"):
        module.pipeline(config, output, resume=True)
