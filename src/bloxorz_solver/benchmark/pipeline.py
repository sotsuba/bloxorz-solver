"""Resource-aware, resumable stress pipeline with isolated sequential measurements."""

import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from bloxorz_solver.benchmark.core import digest
from bloxorz_solver.benchmark.experiments import experiment_id, experiments
from bloxorz_solver.benchmark.runner import SOLVERS, environment, read_manifest, run_one
from bloxorz_solver.benchmark.stress import FAMILIES


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def source_hash():
    root = Path(__file__).resolve().parents[1]
    return digest(
        {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py"))
        }
    )


def available_memory():
    values = {
        line.split(":")[0]: int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
    }
    return values.get("MemAvailable", values["MemTotal"])


def cgroup_directory():
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            # Some containers expose their own cgroup as the mount root.
            candidate = Path("/sys/fs/cgroup") / line[3:].lstrip("/")
            if candidate.exists() and ".." not in candidate.parts:
                return candidate
    return Path("/sys/fs/cgroup")


def hardware_limits(memory_mib=1024):
    cpus = len(os.sched_getaffinity(0))
    memory = available_memory()
    group = cgroup_directory()
    cpu_file, mem_file = group / "cpu.max", group / "memory.max"
    if cpu_file.exists():
        quota, period = cpu_file.read_text().split()
        if quota != "max":
            cpus = min(cpus, max(1, math.ceil(int(quota) / int(period))))
    if mem_file.exists() and mem_file.read_text().strip() != "max":
        used_file = group / "memory.current"
        used = int(used_file.read_text()) if used_file.exists() else 0
        memory = min(memory, max(0, int(mem_file.read_text()) - used))
    capacity = int(memory * 0.75) // (memory_mib * 1024**2)
    if capacity < 1:
        raise ValueError("Insufficient available RAM for one bounded worker")
    return {
        "effective_cpus": cpus,
        "available_memory_bytes": memory,
        "worker_memory_mib": memory_mib,
        "workers": min(max(1, cpus - 1), capacity),
    }


def _cpu_sample():
    values = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3] + values[4]


def candidate_worker(job):
    import resource

    from bloxorz_solver.benchmark.stress import evaluate_candidate

    cap = job["memory_mib"] * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    try:
        return {"status": "accepted", **evaluate_candidate(job)}
    except MemoryError:
        return {"status": "memory_limit"}
    except ValueError as exc:
        return {"status": "rejected", "reason": str(exc)}
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def jobs_for(settings):
    jobs = []
    for attempt in range(settings["attempts_per_slot"]):
        for fi, family in enumerate(FAMILIES):
            for tier in range(3):
                for slot in range(settings["per_cell"]):
                    seed = (
                        settings["seed"] + fi * 1_000_000 + tier * 100_000 + slot * 1000 + attempt
                    )
                    jobs.append(
                        {
                            "index": len(jobs),
                            "family": family,
                            "tier": tier,
                            "slot": slot,
                            "root_id": f"{family}-{tier}-{slot}-{seed}",
                            "seed": seed,
                            "seconds": settings["certification_seconds"],
                            "max_states": settings["max_states"],
                            "memory_mib": settings["memory_mib"],
                        }
                    )
    return jobs


def build_parallel(output, settings, hardware, deadline, checkpoint):
    job_dir, corpus = output / "jobs", output / "corpus"
    job_dir.mkdir(exist_ok=True)
    corpus.mkdir(exist_ok=True)
    (corpus / "levels").mkdir(exist_ok=True)
    jobs = jobs_for(settings)
    records, identities, occupied = [], set(), set()
    v1 = Path(settings["exclude_corpus"])
    if v1.exists():
        identities.update(r["canonical_hash"] for r in read_manifest(v1)["records"])
    pending, completed = {}, {}
    next_submit = next_commit = 0
    previous_cpu, last_sample = _cpu_sample(), 0
    stats = []

    def slot_key(job):
        return job["family"], job["tier"], job["slot"]

    def accept(job, result):
        key = slot_key(job)
        if key in occupied or result["status"] != "accepted":
            return
        if result["canonical_hash"] in identities:
            return
        data = result["data"]
        file = f"levels/{data['id']}.json"
        write_json(corpus / file, data)
        records.append(
            {
                "id": data["id"],
                "file": file,
                "hash": result["hash"],
                "canonical_hash": result["canonical_hash"],
                "family": job["family"],
                "tier": job["tier"],
                "band": job["tier"],
                "root_id": job["root_id"],
                "seed": job["seed"],
                "partition": "development" if job["slot"] == 0 else "evaluation",
                "cohort": result["cohort"],
                "certificate": result["certificate"],
                "witness": result["witness"],
                "necessity": result["necessity"],
                "bridges": len(data["bridges"]),
                "switches": len(data["switches"]),
                "width": len(data["grid"][0]),
                "height": len(data["grid"]),
            }
        )
        occupied.add(key)
        identities.add(result["canonical_hash"])

    target = 9 * settings["per_cell"]
    telemetry = output / "resources.jsonl"
    try:
        while time.monotonic() < deadline and next_commit < len(jobs) and len(records) < target:
            while len(pending) + len(completed) < hardware["workers"] and next_submit < len(jobs):
                job = jobs[next_submit]
                index = next_submit
                next_submit += 1
                cache = job_dir / f"{index:06}.json"
                if cache.exists():
                    completed[index] = json.loads(cache.read_text())
                elif slot_key(job) in occupied:
                    completed[index] = {"status": "slot_full"}
                else:
                    stream = (job_dir / f"{index:06}.out").open("w")
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "bloxorz_solver.benchmark.pipeline",
                            "_worker",
                            json.dumps(job),
                        ],
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                    )
                    pending[index] = (process, stream, time.monotonic())
            for index, (process, stream, started) in list(pending.items()):
                if time.monotonic() - started > settings["certification_seconds"] * 4 + 15:
                    process.kill()
                    process.wait()
                if process.poll() is not None:
                    stream.close()
                    raw = job_dir / f"{index:06}.out"
                    try:
                        result = json.loads(raw.read_text())
                    except ValueError:
                        result = {"status": "worker_failed", "returncode": process.returncode}
                    completed[index] = result
                    write_json(job_dir / f"{index:06}.json", result)
                    del pending[index]
            while next_commit in completed:
                result = completed.pop(next_commit)
                accept(jobs[next_commit], result)
                stats.append({"index": next_commit, "status": result["status"]})
                next_commit += 1
            now = time.monotonic()
            if now - last_sample >= 1:
                current_cpu = _cpu_sample()
                total = current_cpu[0] - previous_cpu[0]
                busy = 1 - (current_cpu[1] - previous_cpu[1]) / max(1, total)
                with telemetry.open("a") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "time": time.time(),
                                "phase": "generation",
                                "active_workers": len(pending),
                                "system_cpu_percent": max(0, busy * 100),
                                "available_memory_bytes": available_memory(),
                                "accepted": len(records),
                            }
                        )
                        + "\n"
                    )
                previous_cpu, last_sample = current_cpu, now
                checkpoint["generation_accepted"] = len(records)
                write_json(output / "checkpoint.json", checkpoint)
            time.sleep(0.02)
    finally:
        # No generator is allowed to overlap a formal timing measurement.
        for process, stream, _ in pending.values():
            if process.poll() is None:
                process.kill()
            process.wait()
            stream.close()
    shortfalls = {
        f"{f}-{t}": settings["per_cell"] - sum(r["family"] == f and r["tier"] == t for r in records)
        for f in FAMILIES
        for t in range(3)
    }
    manifest = {
        "schema_version": 2,
        "generator_version": "2.0",
        "settings": settings,
        "records": records,
        "shortfalls": shortfalls,
        "generation": stats,
        "max_states": settings["max_states"],
        "ci_ids": [r["id"] for r in records if r["partition"] == "development"],
    }
    manifest["corpus_hash"] = digest(manifest)
    write_json(corpus / "manifest.json", manifest)
    checkpoint["corpus_hash"], checkpoint["corpus_frozen"] = manifest["corpus_hash"], True
    write_json(output / "checkpoint.json", checkpoint)
    return manifest


def export_csv(rows, path):
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
            for row in rows
        )


def validate_settings(settings):
    defaults = {
        "seed": 20261021,
        "per_cell": 4,
        "attempts_per_slot": 20,
        "max_states": 1_000_000,
        "certification_seconds": 30,
        "memory_mib": 1024,
        "repeats": 3,
        "search_seconds": 5,
        "generation_seconds": 1080,
        "measurement_seconds": 2280,
        "figure_seconds": 240,
        "total_seconds": 3600,
        "exclude_corpus": "benchmarks/v1",
        "heuristics": ["manhattan"],
    }
    if set(settings) - set(defaults):
        raise ValueError("Unknown pipeline configuration key")
    merged = defaults | settings
    if any(
        not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0
        for k, v in merged.items()
        if k not in ("seed", "exclude_corpus", "heuristics")
    ):
        raise ValueError("Pipeline limits must be positive numbers")
    if merged["per_cell"] < 2 or merged["memory_mib"] < 64:
        raise ValueError("per_cell >= 2 and memory_mib >= 64 required")
    if (
        sum(merged[k] for k in ("generation_seconds", "measurement_seconds", "figure_seconds"))
        > merged["total_seconds"]
    ):
        raise ValueError("Phase budgets exceed total budget")
    if not isinstance(merged["heuristics"], list):
        raise ValueError("heuristics must be a list of names or module:function factories")
    experiments(SOLVERS, merged["heuristics"])
    return merged


def pipeline(config, output, *, resume=False, font_dir=None):
    if sys.platform != "linux":
        raise ValueError("Pipeline resource controls require Linux")
    settings = validate_settings(json.loads(config.read_text()))
    variants = experiments(SOLVERS, settings["heuristics"])
    by_id = {variant["id"]: variant for variant in variants}
    fingerprint = digest({"source": source_hash(), "experiments": variants})
    start = time.monotonic()
    deadline = start + settings["total_seconds"]
    if resume:
        checkpoint = json.loads((output / "checkpoint.json").read_text())
        if (
            checkpoint["config_hash"] != digest(settings)
            or checkpoint["source_hash"] != fingerprint
        ):
            raise ValueError("Resume rejected: source/configuration differs from checkpoint")
    else:
        if output.exists():
            raise ValueError("Output already exists; use --resume")
        output.mkdir(parents=True)
        checkpoint = {
            "config_hash": digest(settings),
            "source_hash": fingerprint,
            "corpus_frozen": False,
            "invocations": [],
        }
    hardware = hardware_limits(settings["memory_mib"])
    checkpoint["hardware"] = hardware
    write_json(output / "checkpoint.json", checkpoint)
    print(
        f"Generation workers: {hardware['workers']}; RAM per worker: {settings['memory_mib']} MiB",
        flush=True,
    )
    if checkpoint["corpus_frozen"]:
        manifest = read_manifest(output / "corpus")
        if manifest["corpus_hash"] != checkpoint["corpus_hash"]:
            raise ValueError("Resume rejected: corpus hash changed")
    else:
        manifest = build_parallel(
            output,
            settings,
            hardware,
            min(deadline - settings["figure_seconds"], start + settings["generation_seconds"]),
            checkpoint,
        )
    results = output / "results"
    results.mkdir(exist_ok=True)
    records = [r for r in manifest["records"] if r["partition"] == "evaluation"]
    metadata = {
        "corpus_hash": manifest["corpus_hash"],
        "source_hash": fingerprint,
        "environment": environment(),
        "hardware": hardware,
        "settings": settings,
        "selected_ids": [r["id"] for r in records],
        "solvers": list(SOLVERS),
        "experiments": variants,
        "measurement_scope": "solver_initialization_and_search",
        "repeats": settings["repeats"],
        "timeout": settings["search_seconds"],
        "memory_mib": settings["memory_mib"],
        "partition": "evaluation",
        "cost_mode": "unit",
    }
    raw = results / "runs.jsonl"
    rows = [json.loads(s) for s in raw.read_text().splitlines()] if raw.exists() else []

    def key(row):
        return row["id"], experiment_id(row), row["mode"], row["repetition"]

    completed = {
        key(row): row for row in rows if row["status"] not in ("not_run", "budget_exhausted")
    }
    jobs = [
        (r, s, mode, rep)
        for r in records
        for s in by_id
        for mode, count in (("timing", settings["repeats"]), ("memory", 1))
        for rep in range(count)
    ]
    import random

    random.Random(settings["seed"]).shuffle(jobs)
    measurement_end = min(
        deadline - settings["figure_seconds"], time.monotonic() + settings["measurement_seconds"]
    )
    with raw.open("a") as stream:
        for index, (record, solver, mode, rep) in enumerate(jobs):
            row = {
                "id": record["id"],
                "solver": by_id[solver]["solver"],
                "experiment": solver,
                "heuristic": by_id[solver]["heuristic"],
                "mode": mode,
                "repetition": rep,
                "family": record["family"],
                "tier": record["tier"],
                "band": record["tier"],
                "cohort": record["cohort"],
                "partition": "evaluation",
                "order": index,
            }
            if key(row) in completed:
                continue
            if time.monotonic() + settings["search_seconds"] + 5 >= measurement_end:
                break
            result = run_one(
                {
                    "level": str((output / "corpus" / record["file"]).resolve()),
                    "solver": by_id[solver]["solver"],
                    "experiment": solver,
                    "heuristic": by_id[solver]["heuristic"],
                    "mode": mode,
                    "timeout": settings["search_seconds"],
                    "memory_mib": settings["memory_mib"],
                    "reference": record["certificate"],
                }
            )
            row.update(result)
            completed[key(row)] = row
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            if len(completed) % 20 == 0:
                print(f"Measurement: {len(completed)}/{len(jobs)}", flush=True)
    all_rows = []
    for record, solver, mode, rep in jobs:
        identity = record["id"], solver, mode, rep
        all_rows.append(
            completed.get(
                identity,
                {
                    "id": record["id"],
                    "solver": by_id[solver]["solver"],
                    "experiment": solver,
                    "heuristic": by_id[solver]["heuristic"],
                    "mode": mode,
                    "repetition": rep,
                    "family": record["family"],
                    "tier": record["tier"],
                    "band": record["tier"],
                    "cohort": record["cohort"],
                    "partition": "evaluation",
                    "status": "not_run",
                },
            )
        )
    export_csv(all_rows, results / "runs.csv")
    write_json(results / "planned-results.json", all_rows)
    metadata["completed_jobs"], metadata["planned_jobs"] = len(completed), len(jobs)
    write_json(results / "metadata.json", metadata)
    # Figure rendering is another bounded process, and cannot extend the deadline.
    command = [
        sys.executable,
        "-m",
        "bloxorz_solver.benchmark.runner",
        "figures",
        "--corpus",
        str(output / "corpus"),
        "--results",
        str(results),
        "--output",
        str(output / "figures"),
    ]
    if font_dir:
        command += ["--font-dir", str(font_dir)]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(0.01, min(settings["figure_seconds"], deadline - time.monotonic())),
        )
        figures = {
            "status": "complete" if result.returncode == 0 else "blocked",
            "message": result.stdout + result.stderr,
        }
    except subprocess.TimeoutExpired:
        figures = {"status": "budget_exhausted"}
    checkpoint["figures"] = figures
    checkpoint["invocations"].append(
        {
            "elapsed_seconds": time.monotonic() - start,
            "completed_jobs": len(completed),
            "planned_jobs": len(jobs),
        }
    )
    write_json(output / "checkpoint.json", checkpoint)
    print(
        f"Corpus: {len(manifest['records'])}; measurements: {len(completed)}/{len(jobs)}; figures: {figures['status']}",
        flush=True,
    )
    return checkpoint


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_worker":
        print(json.dumps(candidate_worker(json.loads(sys.argv[2])), ensure_ascii=False))
