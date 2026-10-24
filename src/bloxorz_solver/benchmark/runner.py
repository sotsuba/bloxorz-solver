"""Bounded subprocess experiments, integrity checking and portable raw results."""

import argparse
import csv
import importlib.metadata
import json
import os
import platform
import random
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from bloxorz_solver.benchmark.core import canonical, certify, digest, replay
from bloxorz_solver.benchmark.experiments import experiments
from bloxorz_solver.benchmark.measure import measure_solver
from bloxorz_solver.levels.loader import load_level
from bloxorz_solver.solvers.heuristics import DEFAULT_HEURISTIC, create_heuristic

SOLVERS = ("bfs", "dfs", "ucs", "astar")


def read_manifest(corpus: Path) -> dict:
    manifest = json.loads((corpus / "manifest.json").read_text())
    expected = manifest.pop("corpus_hash")
    if digest(manifest) != expected:
        raise ValueError("Corpus manifest hash mismatch")
    manifest["corpus_hash"] = expected
    ids, identities = set(), set()
    for record in manifest["records"]:
        path = (corpus / record["file"]).resolve()
        if not path.is_relative_to(corpus.resolve()):
            raise ValueError("Level path escapes corpus")
        data = json.loads(path.read_text())
        if digest(data) != record["hash"]:
            raise ValueError(f"Level hash mismatch: {record['id']}")
        if record["id"] in ids or record["canonical_hash"] in identities:
            raise ValueError("Duplicate corpus identity")
        ids.add(record["id"])
        identities.add(record["canonical_hash"])
    return manifest


def verify_corpus(corpus: Path):
    manifest = read_manifest(corpus)
    for record in manifest["records"]:
        level = load_level(corpus / record["file"])
        if manifest.get("schema_version") == 2:
            from bloxorz_solver.benchmark.stress import oracle

            if canonical(level) != record["canonical_hash"] or not replay(level, record["witness"]):
                raise ValueError(f"Invalid v2 witness/identity: {level.id}")
            certificate = record["certificate"]
            if certificate["path"] is not None and not replay(level, certificate["path"]):
                raise ValueError(f"Invalid v2 certificate path: {level.id}")
            if certificate["status"] == "optimal":
                reference = oracle(level, max_states=manifest["max_states"], seconds=30)
                if (
                    reference["status"] != "optimal"
                    or reference["optimal_length"] != certificate["optimal_length"]
                ):
                    raise ValueError(
                        f"Optimality verification inconclusive or mismatched: {level.id}"
                    )
            if record["cohort"] == "standard":
                for mechanism in record["necessity"]:
                    counter = oracle(
                        level,
                        max_states=manifest["max_states"],
                        seconds=30,
                        forbidden_split=mechanism == "split",
                        forbidden_bridge=None if mechanism == "split" else mechanism,
                    )
                    if counter["status"] != "exhausted":
                        raise ValueError(f"Mechanism verification inconclusive: {level.id}")
            continue
        if canonical(level) != record["canonical_hash"]:
            raise ValueError(f"Canonical identity mismatch: {level.id}")
        reference = certify(level, manifest["max_states"])
        if asdict(reference) != record["certificate"]:
            raise ValueError(f"Certificate mismatch: {level.id}")
        if reference.path is not None and not replay(level, reference.path):
            raise ValueError(f"Invalid witness: {level.id}")
        if record["family"] in ("fragile", "switch", "split"):
            if (
                certify(level, manifest["max_states"], forbidden=record["family"]).status
                != "exhausted"
            ):
                raise ValueError(f"Mechanism is unnecessary: {level.id}")
    return len(manifest["records"])


class SearchTimeout(Exception):
    pass


def worker(payload: dict) -> dict:
    """Run inside a fresh interpreter; POSIX limits cover actual search execution."""
    import resource
    import signal

    from bloxorz_solver.solvers.astar import AStarSolver
    from bloxorz_solver.solvers.bfs import BFSSolver
    from bloxorz_solver.solvers.dfs import DFSSolver
    from bloxorz_solver.solvers.problem import BloxorzProblem
    from bloxorz_solver.solvers.ucs import UCSSolver

    limit = payload["memory_mib"] * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    started = time.perf_counter()
    try:
        level = load_level(payload["level"])
        problem = BloxorzProblem(level)
        constructors = {"bfs": BFSSolver, "dfs": DFSSolver, "ucs": UCSSolver, "astar": AStarSolver}
        loading_seconds = time.perf_counter() - started

        def construct():
            if payload["solver"] == "ucs":
                return UCSSolver(problem, cost_mode="unit")
            if payload["solver"] == "astar":
                heuristic = create_heuristic(payload.get("heuristic", DEFAULT_HEURISTIC), problem)
                return AStarSolver(problem, heuristic=heuristic)
            return constructors[payload["solver"]](problem)

        def expired(signum, frame):
            raise SearchTimeout()

        signal.signal(signal.SIGALRM, expired)
        search_started = time.perf_counter()
        signal.setitimer(signal.ITIMER_REAL, payload["timeout"])
        try:
            result = measure_solver(construct, problem.initial_state, mode=payload["mode"])
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        status = "solved" if result.is_found else "exhausted"
        if result.path is not None and not replay(level, result.path):
            status = "invalid_path"
        reference = payload["reference"]
        known_solvable = reference["status"] in ("solved", "optimal", "witness")
        known_optimal = reference["status"] in ("solved", "optimal")
        if result.path is None and known_solvable:
            status = "error"
        if result.path is not None and (
            not known_solvable
            or (
                known_optimal
                and payload["solver"] != "dfs"
                and len(result.path) != len(reference["path"])
            )
        ):
            status = "error"
        return {
            "status": status,
            "search_time": result.search_time,
            "initialization_time": result.initialization_time,
            "total_time": result.total_time,
            "loading_time": loading_seconds,
            "peak_memory": result.peak_memory,
            "expanded_nodes": result.expanded_nodes,
            "path": result.path,
            "solution_length": result.solution_length if result.is_found else None,
            "length_ratio": len(result.path) / len(reference["path"])
            if status == "solved" and known_optimal and reference["path"]
            else None,
        }
    except SearchTimeout:
        return {"status": "timeout", "elapsed_search": time.perf_counter() - search_started}
    except MemoryError:
        return {"status": "memory_limit"}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def run_one(payload: dict) -> dict:
    started = time.perf_counter()
    try:
        child = subprocess.run(
            [sys.executable, "-m", "bloxorz_solver.benchmark.runner", "_worker"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=payload["timeout"] + 5,
        )
        if child.returncode:
            result = {
                "status": "error",
                "error": child.stderr[-2000:],
                "returncode": child.returncode,
            }
        else:
            result = json.loads(child.stdout)
    except subprocess.TimeoutExpired:
        # subprocess.run kills and waits for its child before raising.
        result = {"status": "timeout", "error": "Worker wall-clock guard expired"}
    except (ValueError, OSError) as exc:
        result = {"status": "error", "error": str(exc)}
    result["worker_wall_time"] = time.perf_counter() - started
    return result


def environment():
    def git(*args):
        result = subprocess.run(["git", *args], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None

    return {
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "cpu_info": Path("/proc/cpuinfo").read_text().split("\n\n")[0],
        "memory_info": Path("/proc/meminfo").read_text().splitlines()[0],
        "revision": git("rev-parse", "HEAD"),
        "dirty_status": git("status", "--short"),
        "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
    }


def run_benchmark(
    corpus,
    output,
    *,
    partition="evaluation",
    repeats=3,
    timeout=10.0,
    memory_mib=1024,
    seed=42,
    solvers=SOLVERS,
    heuristics=(DEFAULT_HEURISTIC,),
):
    if sys.platform != "linux":
        raise ValueError("Resource-limited benchmark runner currently requires Linux")
    if repeats < 1 or timeout <= 0 or memory_mib < 64:
        raise ValueError("repeats >= 1, timeout > 0 and memory_mib >= 64 are required")
    variants = experiments(solvers, heuristics)
    manifest = read_manifest(corpus)
    records = [
        r
        for r in manifest["records"]
        if partition == "all"
        or (partition == "ci" and r["id"] in manifest["ci_ids"])
        or r["partition"] == partition
    ]
    if not records:
        raise ValueError("No records selected")
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    output.mkdir(parents=True)
    metadata = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_hash": manifest["corpus_hash"],
        "environment": environment(),
        "partition": partition,
        "repeats": repeats,
        "timeout": timeout,
        "memory_mib": memory_mib,
        "seed": seed,
        "solvers": list(solvers),
        "experiments": variants,
        "measurement_scope": "solver_initialization_and_search",
        "cost_mode": "unit",
        "selected_ids": [r["id"] for r in records],
    }
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    jobs = [
        (r, variant, "timing", rep)
        for r in records
        for variant in variants
        for rep in range(repeats)
    ]
    jobs += [(r, variant, "memory", 0) for r in records for variant in variants]
    random.Random(seed).shuffle(jobs)
    rows = []
    with (output / "runs.jsonl").open("w") as stream:
        for index, (record, variant, mode, rep) in enumerate(jobs):
            payload = {
                "level": str((corpus / record["file"]).resolve()),
                "solver": variant["solver"],
                "heuristic": variant["heuristic"],
                "timeout": timeout,
                "memory_mib": memory_mib,
                "mode": mode,
                "reference": record["certificate"],
            }
            result = run_one(payload)
            row = {
                "id": record["id"],
                "family": record["family"],
                "band": record["band"],
                "partition": record["partition"],
                "solver": variant["solver"],
                "experiment": variant["id"],
                "heuristic": variant["heuristic"],
                "mode": mode,
                "repetition": rep,
                "order": index,
                **result,
            }
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            if (index + 1) % 100 == 0 or index + 1 == len(jobs):
                print(f"Benchmark: {index + 1}/{len(jobs)}", flush=True)
    fields = sorted({key for row in rows for key in row})
    with (output / "runs.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {k: json.dumps(v) if isinstance(v, list) else v for k, v in r.items()} for r in rows
        )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Kiểm chứng và đo hiệu năng Bloxorz")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("_worker", help=argparse.SUPPRESS)
    verify = sub.add_parser("verify")
    verify.add_argument("--corpus", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--corpus", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument(
        "--partition",
        choices=["all", "development", "evaluation", "negative", "ci"],
        default="evaluation",
    )
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--timeout", type=float, default=10.0)
    run.add_argument("--memory-mib", type=int, default=1024)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--solvers", nargs="+", choices=SOLVERS, default=list(SOLVERS))
    run.add_argument(
        "--heuristics",
        nargs="+",
        default=[DEFAULT_HEURISTIC],
        help="Built-in names or trusted module:function factories for A*",
    )
    sub.add_parser("heuristics", help="List built-in A* heuristics")
    report = sub.add_parser("report")
    report.add_argument("--corpus", type=Path, required=True)
    report.add_argument("--results", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    figures = sub.add_parser("figures", help="Xuất hình khoa học bằng Times New Roman")
    figures.add_argument("--corpus", type=Path, required=True)
    figures.add_argument("--results", type=Path, required=True)
    figures.add_argument("--output", type=Path, required=True)
    figures.add_argument("--font-dir", type=Path)
    pipeline_parser = sub.add_parser("pipeline", help="Pipeline stress có checkpoint")
    pipeline_parser.add_argument("--config", type=Path, required=True)
    pipeline_parser.add_argument("--output", type=Path, required=True)
    pipeline_parser.add_argument("--resume", action="store_true")
    pipeline_parser.add_argument("--font-dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "_worker":
        print(json.dumps(worker(json.load(sys.stdin))))
    elif args.command == "heuristics":
        from bloxorz_solver.solvers.heuristics import HEURISTICS

        for definition in HEURISTICS.values():
            print(f"{definition.name}: {definition.description}")
    elif args.command == "verify":
        print(f"Đã kiểm chứng {verify_corpus(args.corpus)} màn chơi.")
    elif args.command == "run":
        rows = run_benchmark(
            args.corpus,
            args.output,
            partition=args.partition,
            repeats=args.repeats,
            timeout=args.timeout,
            memory_mib=args.memory_mib,
            seed=args.seed,
            solvers=args.solvers,
            heuristics=args.heuristics,
        )
        return int(any(r["status"] in ("error", "invalid_path") for r in rows))
    elif args.command == "pipeline":
        from bloxorz_solver.benchmark.pipeline import pipeline

        checkpoint = pipeline(args.config, args.output, resume=args.resume, font_dir=args.font_dir)
        return int(checkpoint["figures"]["status"] != "complete")
    elif args.command == "figures":
        from bloxorz_solver.benchmark.paper import create_figures

        create_figures(args.corpus, args.results, args.output, font_dir=args.font_dir)
    elif args.command == "report":
        from bloxorz_solver.benchmark.report import create_report

        create_report(args.corpus, args.results, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
