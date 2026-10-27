# Benchmarks

## Run

Requires Linux for worker resource limits.

```sh
uv sync --group dev --extra benchmark
uv run bloxorz-benchmark verify --corpus benchmarks/v1
uv run bloxorz-benchmark run --corpus benchmarks/v1 --output results/quick --partition ci --repeats 1
uv run bloxorz-benchmark report --corpus benchmarks/v1 --results results/quick --output results/report
```

Open `results/report/bao-cao.md` for charts and results. Reports use Vietnamese labels.
Use a new output directory for each run; reports can be regenerated without rerunning solvers.

| Option | Purpose |
|---|---|
| `--partition development` | Tune implementations |
| `--partition evaluation` | Evaluate selected implementations |
| `--partition all` | Run the full corpus, including unsolvable levels |
| `--solvers bfs dfs ucs astar` | Select solvers |
| `--timeout 10` | Limit initialization and search to 10 seconds |
| `--memory-mib 1024` | Cap worker address space |
| `--repeats 3 --seed 42` | Set timing repetitions and run order |

For A* comparisons and custom factories, see [Heuristics](heuristics.md).

## Corpus

`benchmarks/v1` contains 360 solvable and 20 unsolvable levels: ordinary floor,
fragile tiles, bridges/switches, and split blocks. Solvable levels are divided into
120 development and 240 evaluation cases; `ci` selects 12 fixed cases.

Reference BFS certifies shortest paths and reachable graph sizes using the game
engine. Generated levels must require their designated mechanic. Deduplication
accounts for translation, rotation, and reflection. Unsolvable cases have isolated
goals; they do not represent difficult unsolvable puzzles.

Keep v1 fixed. Generate additional corpora separately:

```sh
uv run bloxorz-generate --config configs/benchmark.json --output results/new-corpus
```

Use `configs/benchmark-smoke.json` for a smaller corpus. The manifest records seeds,
configuration, certificates, and generation statistics. Reproduction requires the
same code and environment; seeds alone are insufficient.

## Measurements

All solvers use unit action costs, including cube swaps. Each measurement runs in
a fresh worker; timing and memory are measured separately.

| Field | Meaning |
|---|---|
| `initialization_time` | Solver and heuristic construction |
| `search_time` | Search with memory tracing disabled |
| `total_time` | Initialization plus search |
| `peak_memory` | Peak Python allocations during initialization and search |
| `expanded_nodes` | States expanded, using each solver's counting convention |

Unmeasured fields are null. The address-space cap is distinct from `peak_memory`.
Workers replay solutions and check optimal lengths when certificates are available.
Results record configuration, environment, source revision, and corpus hashes.

Compare costs on levels solved by every selected experiment, and inspect failure
rates separately. Timeouts and errors are not successful timings. DFS may return
longer paths. Older results can measure search only; check their measurement scope
before comparing them with current results.

## Publication figures

```sh
uv run bloxorz-benchmark figures \
  --corpus benchmarks/v1 --results results/quick --output results/figures
```

Requires Times New Roman with Vietnamese glyphs; use `--font-dir PATH` if needed.
Output includes PDF, SVG, PNG, captions, and CSV data. Read `captions.md` for sample
sizes and omitted figures. Figure generation does not rerun solvers.

The corpus favors small, verifiable levels. Results do not establish performance
on all Bloxorz puzzles or measure human difficulty.
