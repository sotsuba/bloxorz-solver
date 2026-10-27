# Bloxorz Solver

Bloxorz with a Pygame interface, BFS, DFS, UCS, A*, and a reproducible benchmark suite.

## Run

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run bloxorz-solver
```

Use `--level path/to/level.json` to open a custom level.
In Manual mode, move with WASD or arrow keys; Space switches the active cube.
Choose a solver and click Solve to solve from the current position.

## Docs

- [Benchmarks](docs/benchmark.md): run experiments, generate levels, export figures.
- [A* heuristics](docs/heuristics.md): built-ins, custom factories, comparisons.
- [Corpus](benchmarks/README.md): dataset layout.
- [Contributing](CONTRIBUTING.md): workflow and checks.
