"""Experiment identities shared by workers, resumable jobs, and report readers."""

import hashlib
import inspect
from pathlib import Path
from textwrap import fill

from bloxorz_solver.solvers.heuristics import DEFAULT_HEURISTIC, HEURISTICS, resolve_heuristic


def axis_label(label):
    """Keep algorithm and heuristic readable in narrow categorical panels."""
    algorithm, separator, heuristic = label.partition(" / ")
    return f"{algorithm}\n{fill(heuristic, width=11)}" if separator else fill(label, width=11)


def experiments(solvers, heuristics=(DEFAULT_HEURISTIC,)):
    solvers, heuristics = list(solvers), list(heuristics)
    if not solvers or len(set(solvers)) != len(solvers):
        raise ValueError("Select distinct solvers")
    if set(solvers) - {"bfs", "dfs", "ucs", "astar"}:
        raise ValueError("Unknown solver")
    if not heuristics or len(set(heuristics)) != len(heuristics):
        raise ValueError("Select distinct heuristics")
    definitions = {}
    if "astar" in solvers:
        for name in heuristics:
            factory = resolve_heuristic(name)
            try:
                source = inspect.getsourcefile(factory)
            except TypeError:
                source = None
            definitions[name] = {
                "factory": f"{factory.__module__}:{factory.__name__}",
                "source_hash": hashlib.sha256(Path(source).read_bytes()).hexdigest()
                if source and Path(source).is_file()
                else None,
            }
    return [
        {
            "id": f"astar:{name}" if solver == "astar" else solver,
            "solver": solver,
            "heuristic": name,
            "label": f"A* / {HEURISTICS[name].label if name in HEURISTICS else name}"
            if solver == "astar"
            else solver.upper(),
            **(definitions[name] if solver == "astar" else {}),
        }
        for solver in solvers
        for name in (heuristics if solver == "astar" else [None])
    ]


def experiment_id(row):
    return row.get("experiment", row["solver"])


def report_view(metadata, rows):
    """Adapt new and legacy rows to experiment-keyed reporting without data loss.

    Legacy ``astar`` denotes the original Manhattan bound. Raw rows retain their
    algorithm in ``solver``; this reporting copy groups by experiment instead.
    """
    definitions = metadata.get("experiments")
    if not definitions:
        definitions = [
            {"id": s, "label": "A* / Manhattan" if s == "astar" else s.upper()}
            for s in metadata["solvers"]
        ]
    ids = [definition["id"] for definition in definitions]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate experiment definition")
    if metadata.get("experiments"):
        by_id = {definition["id"]: definition for definition in definitions}
        for row in rows:
            definition = by_id.get(experiment_id(row))
            if (
                definition is None
                or row["solver"] != definition["solver"]
                or (row.get("heuristic") != definition.get("heuristic"))
            ):
                raise ValueError("Unexpected or mismatched experiment row")
    return (
        {**metadata, "solvers": ids},
        [{**row, "algorithm": row["solver"], "solver": experiment_id(row)} for row in rows],
        {definition["id"]: definition["label"] for definition in definitions},
    )
