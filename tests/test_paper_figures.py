"""Publication exports use measured cohorts, explicit context and auditable samples."""

import copy
import csv
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")
from matplotlib.figure import Figure

from bloxorz_solver.benchmark import paper
from bloxorz_solver.benchmark.core import digest

CORPUS = Path(__file__).resolve().parents[1] / "benchmarks/v1"


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    # Keep real font/layout/PDF export while avoiding large test-only raster files.
    try:
        font = paper.find_times()
    except ValueError:
        pytest.skip("Times New Roman is required for the publication export")
    monkeypatch.setattr(paper, "find_times", lambda _: font)
    original_save = Figure.savefig

    def small_raster(self, path, **kwargs):
        if str(path).endswith(".png"):
            kwargs["dpi"] = 40
        return original_save(self, path, **kwargs)

    monkeypatch.setattr(Figure, "savefig", small_raster)
    source = json.loads((CORPUS / "manifest.json").read_text())
    base = [
        next(r for r in source["records"] if r["family"] == family)
        for family in ("ordinary", "switch")
    ]
    corpus, runs, output = (tmp_path / name for name in ("corpus", "runs", "figures"))
    corpus.mkdir()
    runs.mkdir()

    def prepare(
        *,
        challenge=False,
        challenge_only=False,
        failed=False,
        missing_memory=False,
        telemetry=False,
    ):
        records = copy.deepcopy(base)
        if challenge:
            record = records[1]
            record["cohort"] = "challenge"
            record["witness"] = record["certificate"]["path"]
            record["tier"] = 1
            record["certificate"] = {
                "status": "bounded",
                "path": None,
                "lower_bound": 1,
                "discovered_states": 42,
            }
        if challenge_only:
            records = records[1:]
        manifest = {"records": records}
        manifest["corpus_hash"] = digest(manifest)
        for record in records:
            path = corpus / record["file"]
            path.parent.mkdir(exist_ok=True)
            shutil.copyfile(CORPUS / record["file"], path)
        (corpus / "manifest.json").write_text(json.dumps(manifest))
        metadata = dict(
            corpus_hash=manifest["corpus_hash"],
            selected_ids=[r["id"] for r in records],
            solvers=["bfs", "dfs"],
            repeats=2,
            timeout=2,
            measurement_scope="solver_initialization_and_search",
            partition="all",
        )
        (runs / "metadata.json").write_text(json.dumps(metadata))
        rows = []
        for record in records:
            length = len(record.get("witness", record["certificate"].get("path")))
            for si, solver in enumerate(metadata["solvers"]):
                for rep in range(2):
                    # Deterministic medians: BFS .013 s total; DFS .023 s total.
                    rows.append(
                        dict(
                            id=record["id"],
                            solver=solver,
                            mode="timing",
                            repetition=rep,
                            status="timeout" if failed else "solved",
                            search_time=0.01 * (si + 1) + 0.002 * rep,
                            initialization_time=0.002,
                            total_time=0.012 + 0.01 * si + 0.002 * rep,
                            expanded_nodes=10 + si,
                            solution_length=length * (si + 1),
                        )
                    )
                rows.append(
                    dict(
                        id=record["id"],
                        solver=solver,
                        mode="memory",
                        repetition=0,
                        status="memory_limit" if missing_memory and si else "solved",
                        peak_memory=None if missing_memory and si else 1024 * 1024,
                    )
                )
        (runs / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        resource_file = tmp_path / "resources.jsonl"
        if telemetry:
            resource_file.write_text(
                "\n".join(
                    json.dumps(
                        dict(
                            time=i * 60,
                            system_cpu_percent=10 + i,
                            available_memory_bytes=1024**3,
                            accepted=i,
                        )
                    )
                    for i in range(2)
                )
            )
        else:
            resource_file.unlink(missing_ok=True)
        return corpus, runs, output

    return prepare


def exported(output):
    manifest = json.loads((output / "figure-manifest.json").read_text())
    guide = (output / "captions.md").read_text()
    figures = manifest["figures"]
    assert [r["number"] for r in figures] == list(range(1, len(figures) + 1))
    for figure in figures:
        for extension in ("png", "svg", "pdf"):
            assert (output / f"{figure['name']}.{extension}").stat().st_size > 0
    for target in re.findall(r"\]\(([^)]+)\)", guide):
        assert (output / target).is_file(), target
    if shutil.which("pdfinfo"):
        info = subprocess.check_output(["pdfinfo", str(output / "bo-hinh.pdf")], text=True)
        assert int(re.search(r"Pages:\s+(\d+)", info)[1]) == len(figures)
    return manifest, guide


def test_standard_figures_explain_context_and_use_common_samples(experiment):
    corpus, runs, output = experiment(missing_memory=True)
    paper.create_figures(corpus, runs, output)
    manifest, guide = exported(output)
    assert len(manifest["figures"]) == 4
    assert manifest["figures"][0]["name"] == "01-hieu-nang"
    assert not (output / "05-do-phu.png").exists()
    assert manifest["common_success_maps"] == 2
    assert {r["name"] for r in manifest["skipped"]} >= {
        "panels-challenge",
        "04-khoang-nghiem",
        "07-tai-nguyen",
    }
    assert "Mục tiêu và phạm vi" in guide and "Cách đọc:" in guide
    assert "**Quan sát từ dữ liệu:**" in guide and "Giới hạn khi diễn giải" in guide
    assert "13.000" in guide and "23.000" in guide
    with (output / "data/01-hieu-nang.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert all(r["metric"] != "peak_memory" for r in rows)  # no solver-specific memory cohort
    assert all(int(r["sample_count"]) == 2 for r in rows)
    assert sorted(
        {float(r["median"]) for r in rows if r["metric"] == "total_time"}
    ) == pytest.approx([13, 23])
    assert "n=0" in (output / "01-hieu-nang.svg").read_text()


def test_mixed_cohorts_include_witnessed_challenges_and_cleanup_on_rerun(experiment):
    corpus, runs, output = experiment(challenge=True, telemetry=True)
    paper.create_figures(corpus, runs, output)
    manifest, guide = exported(output)
    assert len(manifest["figures"]) == 6
    with (output / "data/02-ty-le-giai.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert {r["cohort"] for r in rows} == {"standard", "challenge"}
    assert all(int(r["denominator"]) == 1 for r in rows)
    with (output / "data/04-khoang-nghiem.csv").open() as stream:
        bounds = list(csv.DictReader(stream))
    assert bounds[0]["label"] == "M01" and bounds[0]["best_observed"]
    assert "6. Tài nguyên" in guide
    user_file = output / "notes.txt"
    user_file.write_text("Keep this file")
    corpus, runs, output = experiment()
    paper.create_figures(corpus, runs, output)
    manifest, _ = exported(output)
    assert len(manifest["figures"]) == 4
    for name in ("04-khoang-nghiem", "07-tai-nguyen"):
        for extension in ("png", "svg", "pdf"):
            assert not (output / f"{name}.{extension}").exists()
        assert not (output / f"data/{name}.csv").exists()
    assert user_file.read_text() == "Keep this file"


def test_failed_runs_have_zero_success_rate_without_fake_costs(experiment):
    corpus, runs, output = experiment(failed=True)
    paper.create_figures(corpus, runs, output)
    manifest, guide = exported(output)
    assert manifest["common_success_maps"] == 0
    assert manifest["status_counts"]["timeout"] == 8
    assert "01-hieu-nang" not in {r["name"] for r in manifest["figures"]}
    assert "n=0" in guide and "Không có mẫu thành công chung" in guide
    with (output / "data/02-ty-le-giai.csv").open() as stream:
        cdf = list(csv.DictReader(stream))
    assert all(float(r["percent"]) == 0 and int(r["denominator"]) == 2 for r in cdf)


def test_challenge_only_partial_runs_keep_denominator_and_missing_status(experiment):
    corpus, runs, output = experiment(challenge=True, challenge_only=True)
    rows = [json.loads(line) for line in (runs / "runs.jsonl").read_text().splitlines()]
    rows = [
        r
        for r in rows
        if not (r["solver"] == "bfs" and r["mode"] == "timing" and r["repetition"] == 1)
    ]
    (runs / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    paper.create_figures(corpus, runs, output)
    manifest, guide = exported(output)
    assert manifest["not_run"] == 1
    assert manifest["common_success_maps"] == 0
    assert "panels-standard" in {r["name"] for r in manifest["skipped"]}
    assert "Lượt chưa chạy: **1**" in guide
    with (output / "data/02-ty-le-giai.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert {r["cohort"] for r in rows} == {"challenge"}
    assert all(int(r["denominator"]) == 1 for r in rows)
    assert max(float(r["percent"]) for r in rows if r["solver"] == "bfs") == 0
    assert max(float(r["percent"]) for r in rows if r["solver"] == "dfs") == 100
