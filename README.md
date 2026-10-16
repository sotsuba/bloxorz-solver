# bloxorz-solver

Bloxorz in Pygame, with ten playable stages and a game model that plugs into the
solver interfaces in `src/bloxorz_solver/solvers`.

## Run

Use Python 3.10 or newer and [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run bloxorz-solver
```

You can also run `uv run python -m bloxorz_solver` or `uv run python main.py`.
Open an external stage with:

```sh
uv run bloxorz-solver --level path/to/level.json
```

| Control | Action |
| --- | --- |
| Arrows / WASD | Roll the block or move the active cube |
| Space | Switch the active cube after splitting |
| R | Restart the current stage |
| Page Up / Page Down | Select a stage |
| Enter | Start the selected stage |
| N | Advance after completing a stage |
| O | Enter the path to a JSON level |
| Escape | Cancel path entry, or quit |

Mouse controls are available in the sidebar. You can also drop a JSON level onto
the window. Roll upright into the goal to win. Orange tiles break under an upright
block; switches control bridges or split the block into independently movable cubes.

## Source layout

All application code lives in `src/bloxorz_solver`:

- `game/state.py`: immutable board, block, and mechanism values. A `GameState`
  includes cube selection and bridge configuration, and can be used in sets/dicts.
- `game/rules.py`: deterministic movement, switches, split/merge, and win/loss rules.
- `game/session.py`: manual-play state, counters, restart, and terminal outcomes.
- `game/validation.py`: checks static level invariants.
- `levels/loader.py` and `levels/*.json`: validated external levels and bundled stages.
- `solvers/`: the existing contracts/base class plus the Bloxorz problem adapter.
- `ui/app.py`: event loop, input dispatch, and stage/session lifecycle.
- `ui/view.py`: window layout, controls, text, and pointer-coordinate mapping.
- `ui/board.py`: Pygame board rendering.
- `ui/animation.py` and `ui/motion.py`: animation timing and geometry without Pygame.
- `cli.py`: command-line arguments and application startup.

`game`, `levels`, and `solvers` do not import Pygame. The interface and the search
adapter use `safe_transitions` from the same rules, so algorithms do not need to
duplicate movement logic. Both legal-action queries and solver expansion exclude
terminal and unsupported states.

## Connect a solver

`BloxorzProblem` implements the existing `SearchProblem` protocol without changing
`BaseSolver`, `SearchResult`, or `Transition`:

```python
from bloxorz_solver.levels.loader import builtin_levels
from bloxorz_solver.solvers.contracts import SearchProblem
from bloxorz_solver.solvers.problem import BloxorzProblem

problem = BloxorzProblem(builtin_levels()[0])
search_problem: SearchProblem = problem
state = problem.initial_state

for edge in search_problem.get_successors(state):
    print(edge.action, edge.next_state, edge.cost)
```

For any algorithm subclassing `BaseSolver`, call
`YourSolver(problem).solve(problem.initial_state)`. Implement `_search(initial_state)`
to return `(path, expanded_nodes)`; the base class supplies timing, memory metrics,
and path reconstruction.

Actions are `"up"`, `"down"`, `"left"`, `"right"`, and `"swap"`. Each edge costs
`1.0`, including cube swaps. Successors exclude invalid and losing moves; won or
unsupported states have no successors. States contain only dynamic game data; the
problem owns the static level. A found result can be replayed using
`session.apply_action(Action(action))` for each string in `result.path`.

The desktop app currently provides manual play. Concrete search algorithms and
solver playback controls are not implemented yet.

## Test

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests use SDL's dummy display and audio drivers, so no desktop is required. They
cover rules, all ten winning routes, Pygame events/rendering/animation, and the
adapter's compatibility with the existing solver base.

Before contributing, read [CONTRIBUTING.md](CONTRIBUTING.md).
