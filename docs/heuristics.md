# A* heuristic experiments

A* accepts any callable with the signature `heuristic(state) -> float`. For
level-specific preprocessing and command-line selection, use a factory with the
signature `factory(problem: BloxorzProblem) -> Heuristic`.

```python
from bloxorz_solver.solvers.astar import AStarSolver
from bloxorz_solver.solvers.heuristics import create_heuristic
from bloxorz_solver.solvers.problem import BloxorzProblem

problem = BloxorzProblem(level)
estimate = create_heuristic("relaxed_board", problem)
result = AStarSolver(problem, heuristic=estimate).solve(problem.initial_state)
```

Calling `AStarSolver(problem)` still uses the problem's existing Manhattan bound.
For generic search problems without a heuristic method it still uses zero.

## Built-in choices

| Name | Estimate | Preprocessing |
|---|---|---|
| `zero` | Always zero; uniform-cost baseline | None |
| `manhattan` | Existing rounded sum of cube Manhattan distances divided by three | None |
| `euclidean` | Unrounded sum of cube Euclidean distances divided by three | Target list |
| `relaxed_board` | Maximum of Manhattan and relaxed intact-block roll distance | Reverse BFS over board positions/orientations |

Distance targets include the goal and every split switch. Count a standing block
as two cubes at the same coordinate. One roll can reduce the summed distance by
at most three; cube moves reduce it by at most one. Targeting split switches
keeps the bounds valid across split teleports.

The relaxed board treats all bridges as open and fragile floor as unbreakable.
Its terminals are the standing goal pose and standing poses on split switches.
Before the first split or goal, every actual intact-block roll has an edge in
this graph. Its shortest distance is therefore a lower bound on that prefix of
the actual solution. Split states and missing abstract distances use Manhattan.
This avoids enumerating every cube pair or bridge mask. It can be weak on maps
where a nearby split is unnecessary. A* supports inconsistent admissible bounds
by reopening improved states.

All built-ins assume unit-cost actions, including cube swaps. Estimates must be
finite, nonnegative, zero at goals, and no greater than the remaining optimal
cost. A* rejects nonfinite/negative values. Arbitrary custom admissibility cannot
be inferred from the callable: prove the bound and test it against exact small
graphs. Benchmark workers replay paths and check optimal length whenever an exact
certificate exists; witness-only levels establish solvability, not optimality.

## Custom factories without runner changes

Put a factory in an importable module, for example `my_heuristics.py`:

```python
from bloxorz_solver.solvers.heuristics import Heuristic
from bloxorz_solver.solvers.problem import BloxorzProblem

def baseline(problem: BloxorzProblem) -> Heuristic:
    # Precompute level-local data here; capture it in the returned callable.
    return lambda state: 0.0
```

Select `my_heuristics:baseline`. Install the module or set `PYTHONPATH` so it is
importable in both the parent process and fresh worker interpreters. Imports run
trusted Python code. Keep mutable tables inside the factory; avoid global caches
across levels. A named built-in can also be added to `HEURISTICS`, which supplies
its display name and description to the UI and CLI.

## Run a comparison

```sh
uv run bloxorz-benchmark heuristics
uv run bloxorz-benchmark run \
  --corpus benchmarks/v1 --output results/heuristic-dev \
  --partition development --repeats 3 --solvers bfs ucs astar \
  --heuristics zero manhattan euclidean relaxed_board
uv run bloxorz-benchmark report \
  --corpus benchmarks/v1 --results results/heuristic-dev \
  --output results/heuristic-dev-report
uv run bloxorz-benchmark figures \
  --corpus benchmarks/v1 --results results/heuristic-dev \
  --output results/heuristic-dev-figures
```

Add `my_heuristics:baseline` to `--heuristics` after creating that example module.
`--heuristics` defaults to `manhattan` and expands only A* runs. Tune on `development`, then run
the chosen implementations on `evaluation`. Each experiment has a stable identity
such as `astar:relaxed_board`; raw rows retain `solver: astar` and a separate
`heuristic` field. Metadata records factory paths and available source-file hashes.
These hashes identify the factory module, not all transitive dependencies.

Each fresh worker loads its level, then measures solver/heuristic construction
and search under one timeout and address-space cap:

- `loading_time`: level/problem loading outside the measured phase.
- `initialization_time`: solver/heuristic construction, including preprocessing.
- `search_time`: the A* search itself, without tracing.
- `total_time`: initialization plus search in that timing pass.
- `peak_memory`: a separate traced pass covering initialization and search.

Unused timing/memory fields are null. Worker startup is recorded separately as
`worker_wall_time`. Reports and publication figures compare total time for new
results; the report also shows separate initialization/search medians. Compare
costs on the common set solved by all selected experiments, and inspect failure
rates too. Publication CSVs retain initialization, search, and total time.

Older results with plain `astar` are read as Manhattan and retain their original
search-only measurement scope. Their memory numbers exclude preprocessing; do not
compare them directly with the new combined memory scope.

For the resumable stress pipeline, add e.g.
`"heuristics": ["zero", "manhattan", "euclidean", "relaxed_board"]` to its JSON
configuration. Resume rejects changed source, configuration, or factory
fingerprints. It keys completed jobs by experiment, level, mode, and repetition.

## Interactive solving

Select **A*** in **Play mode**, choose a built-in from the **A* heuristic**
dropdown, then **Solve from here**. Factory construction and search run in the
background from the current position. The UI shows elapsed search time and
solution progress; **Show details** reveals initialization time, expanded states,
solution length and peak memory.

**Pause** stops after the current animation; each **Step** click then applies one
action through the normal animation system. **Resume** continues automatically.
Playback speed can be 0.5x, 1x, 2x or 4x without affecting manual play. Browsing
for a file pauses and preserves the route; canceling does not resume it.
Changing heuristic, mode, or active level discards old results and queued actions.
The UI defaults to Manhattan and automatically plays a newly computed route.
