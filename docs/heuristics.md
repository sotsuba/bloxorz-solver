# A* heuristics

## Built-ins

| Name | Estimate | Preprocessing |
|---|---|---|
| `zero` | Zero; uniform-cost baseline | None |
| `manhattan` | Rounded sum of cube Manhattan distances divided by three | None |
| `euclidean` | Sum of cube Euclidean distances divided by three | Target list |
| `relaxed_board` | Maximum of Manhattan and relaxed roll distance | Reverse BFS |

Targets include the goal and split switches. The relaxed board treats bridges as
open and fragile floor as unbreakable; split states or missing distances fall back
to Manhattan. All built-ins assume unit-cost actions, including cube swaps.

```python
from bloxorz_solver.solvers.astar import AStarSolver
from bloxorz_solver.solvers.heuristics import create_heuristic
from bloxorz_solver.solvers.problem import BloxorzProblem

problem = BloxorzProblem(level)
heuristic = create_heuristic("relaxed_board", problem)
result = AStarSolver(problem, heuristic=heuristic).solve(problem.initial_state)
```

`AStarSolver(problem)` uses the problem's heuristic, or zero if absent.
Custom estimates must be finite, nonnegative, zero at goals, and admissible for
optimal solutions. A* reopens improved states to support inconsistent bounds.

## Custom factories

Define an importable factory returning `heuristic(state) -> float`:

```python
# my_heuristics.py
from bloxorz_solver.solvers.problem import BloxorzProblem


def baseline(problem: BloxorzProblem):
    return lambda state: 0.0
```

Pass `my_heuristics:baseline` to `--heuristics`. The module must be importable by
fresh worker processes. Keep level-specific preprocessing inside the factory.
Register a factory in `HEURISTICS` to expose it in the GUI as well.

## Compare

```sh
uv run bloxorz-benchmark heuristics
uv run bloxorz-benchmark run \
  --corpus benchmarks/v1 --output results/heuristics \
  --partition development --repeats 3 --solvers bfs ucs astar \
  --heuristics zero manhattan euclidean relaxed_board
uv run bloxorz-benchmark report \
  --corpus benchmarks/v1 --results results/heuristics \
  --output results/heuristics-report
```

The CLI defaults to `manhattan`; `--heuristics` affects only A*. Results identify
variants separately, such as `astar:relaxed_board`. Tune on `development`, then
validate on `evaluation`. See [Benchmarks](benchmark.md) for measurement details.

In the GUI, select A*, choose a heuristic, and solve from the current position.
Changing the heuristic, mode, or level discards the previous result.
