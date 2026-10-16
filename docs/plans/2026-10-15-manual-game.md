# Bloxorz Manual Game Implementation Plan

**Goal:** Deliver a playable desktop Bloxorz game with all assignment mechanics, without search algorithms.

**Architecture:** Immutable domain models and a pure transition function define the game. A session tracks play status and counters; a JSON loader supplies validated levels; PySide6 renders snapshots and forwards player actions.

**Tech Stack:** Python 3.11+, PySide6, pytest, Ruff, setuptools.

The user approved this plan and the associated file changes, local virtual environment, dependency installation and checks. Implementation stays in this workspace; it is not currently a Git repository. No unavailable execution subskills or separate worktrees are needed.

## 1. Package and conventions

- Create `pyproject.toml`, `requirements.txt`, `.gitignore`, `main.py` and the `src/bloxorz/` package.
- Record edge rules in `docs/gameplay_conventions.md` before implementing them.
- Create the fresh `.venv-game` requested by the user and install the editable package with development dependencies. The earlier incomplete `.venv` is not used.
- Use `QWidget` + `QPainter`; no worker thread is needed for manual play.

## 2. Models and engine

- Create `domain/models.py`, `domain/engine.py`, `domain/validation.py` and `tests/test_engine.py`.
- Test the twelve orientation/direction pairs before implementing rolling.
- Represent normal blocks by their top/left anchor and split blocks by stable A/B positions and active index.
- Represent bridges by a stable bitmask; expose pure `initial_state`, `occupied_cells`, `transition`, `legal_actions` and `is_goal` functions.
- Return explicit moved, won, lost or invalid outcomes. Falling ends manual play; a future search adapter can discard lost outcomes.
- Test bounds, void, fragile support, goal orientation, edge-triggered switches, bridge changes, split/merge, collision and swap.

## 3. Level loading and sample levels

- Create `infrastructure/level_loader.py` and packaged `levels/*.json` resources.
- Reject malformed grids, IDs, references, positions, effects and spawn configurations with useful errors.
- Add at least one winnable stage for basic, fragile, soft/toggle, heavy/set and split/rejoin mechanics.
- Create `tests/test_level_loader.py`; verify every bundled level using a fixed, hand-authored action sequence, without implementing a search algorithm.

## 4. Session

- Create `application/game_session.py` and `tests/test_game_session.py`.
- Track the immutable current state, terminal status, rolls and swaps outside search state.
- Restart restores the initial bridge mask and block; terminal sessions ignore further actions.

## 5. Desktop interface

- Create `presentation/board_widget.py`, `presentation/main_window.py` and `__main__.py`.
- Board-centered layout, a quiet control sidebar, visible tile legend, level description, move counters and persistent outcome banner.
- Palette: slate background `#172D42`, blue-gray floor `#D1DEE6`, brass block `#E9B56A`, turquoise bridge `#48B5AC`, orange fragile `#E58A63`, violet split `#A79ADD`.
- Use the platform sans-serif font with distinct display/body sizes. Board symbols and hatch patterns communicate tile types without relying on color.
- Add level selection, New Game, Restart, arrow/WASD keys, Space to swap, R to restart, and on-screen controls.
- Keep keyboard handling active after clicking controls; do not consume level-selector navigation keys.
- Add offscreen Qt smoke tests for startup, keyboard/buttons, win/loss/restart and split rendering.

## 6. Validate and document

- Create README with actual installation, launch, controls, conventions and tests.
- Run `.venv-game/bin/python -m pytest -q`, `.venv-game/bin/ruff check .` and `.venv-game/bin/ruff format --check .`.
- Render and inspect an offscreen screenshot. Build a wheel and check that levels are packaged.
- No solver stubs, benchmark code or unrelated architecture changes.

## Approved follow-up: dark wood and animation

The user approved this follow-up plan: dark brown timber; rigid quarter-turn movement; accelerated falls into void and the goal; hinged bridge opening/closing; movement input blocked during effects, with immediate cancellation on Restart/New game.

- Add presentation-only solid geometry in `presentation/motion.py`, independently tested against engine endpoints.
- Drive rendering with one owned Qt `QVariantAnimation`; never sleep or change domain rules.
- Keep the engine's committed result separate from the visual frame. Finish the current animation before accepting another action.
- Clip sinking timber against the goal surface; hide fallen timber after the effect completes.
- Test timer progress, repeated input, restart and level change during animation, bridge endpoints and terminal states.
- Inspect rendered motion frames and run pytest, Ruff and format checks in `.venv-game`.

## Approved fix: partial support during falls

- Query supporting cells through the domain engine, using the bridge mask after the move.
- When an intact lying block has one supporting cell, rotate around its shared edge with the unsupported cell, then release the block and drift outwards. Do not translate the supported half down through the platform.
- Keep fully unsupported falls and goal sinking unchanged. For separate cubes, animate only unsupported cubes.
- Check rigid dimensions, continuous phase boundaries and every sampled below-floor face against the support edge; cover all four directions, sideways movement, closed bridges and GUI cancellation.
