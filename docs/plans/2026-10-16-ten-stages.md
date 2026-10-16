# Ten-stage campaign

The user approved enlarging later stages and increasing difficulty across exactly ten stages, covering fragile tiles, bridges, soft/heavy/split switches, splitting/rejoining, toggle bridges and bridges set permanently open or closed. Search remains outside the playable application.

## Implementation plan

1. Preserve the first tutorial and stage IDs 01–06; redesign stages 02–06 and add 07–10 as packaged JSON resources.
2. Increase width, height, usable terrain and shortest winning action count at each stage. Use disconnected islands, narrow bends and dependent switches rather than empty padding alone.
3. Introduce fragile, soft/toggle, heavy/set-open and split/rejoin in sequence. Combine these in later stages; stage 08 introduces set-close and planning before departure. Stages 09–10 require two split/rejoin cycles, with an intact block needed for a heavy switch between them.
4. Audit solvability and bypasses using the real engine, keeping the temporary state traversal tool outside the repository. Store only fixed regression routes in tests.
5. Update session and GUI integration tests affected by the redesigned levels, inspect the largest stage at normal/minimum window sizes and document the campaign.

The domain model, JSON schema, game rules, controls and animation API need no changes.

## Validated progression

Usable cells include floor, fragile, start, goal and bridge cells. Minimum actions include direction changes of the selected cube and swaps; every action has equal cost.

| Stage | Width × height | Usable cells | Minimum actions | Swaps in witness |
| --- | --- | ---: | ---: | ---: |
| 01 | 9 × 5 | 21 | 4 | 0 |
| 02 | 11 × 6 | 22 | 10 | 0 |
| 03 | 12 × 7 | 38 | 11 | 0 |
| 04 | 13 × 8 | 47 | 13 | 0 |
| 05 | 14 × 9 | 48 | 20 | 1 |
| 06 | 16 × 10 | 57 | 25 | 1 |
| 07 | 17 × 11 | 62 | 26 | 0 |
| 08 | 18 × 12 | 70 | 30 | 0 |
| 09 | 20 × 13 | 96 | 45 | 2 |
| 10 | 22 × 14 | 130 | 57 | 2 |

These minima were obtained by breadth-first traversal of immutable engine states, expanding only `MOVED` and `WON` results. The traversal was a temporary level-design check; it is not shipped with the game. Shortest action count is an objective progression measure, not a complete measure of human puzzle difficulty.

## Mechanic and bypass audit

- Every stage has a winning witness. Witnesses activate every switch, cross every bridge and use fragile terrain wherever present.
- Removing any split station or any switch that opens a required bridge leaves its stage without a solution. The audit exhausts reachable valid states; it does not stop at an arbitrary search depth.
- In stages 08 and 10, the set-close switch occupies the required landing path after the first bridge. Blocking that tile leaves no solution. The switch closes the bridge after the block reaches safety.
- Disabling `prepare_exit` leaves stages 08 and 10 unsolvable. The winning witnesses open the exit before closing the return bridge.
- Stage 06 requires a single cube to open the other cube's route. Narrow bends require moving both cubes before a useful reunion.
- Stages 09 and 10 require both split stations. Their witnesses merge, activate the intermediate heavy switch, split again, and merge before entering the goal.
- A direct connection between the first receiving island and the later assembly room was found during the stage-10 audit and removed. The final design requires all seven switches and all four bridges.

Fixed witnesses live in `tests/fixtures/stage_routes.json`; `U`, `D`, `L`, `R` are directional actions and `X` swaps the active cube. Campaign regression tests replay these witnesses and check event order and terrain use. The existing engine tests cover switch edge triggering, bridge effects and fragile support rules.

## Final checks

- All 150 pytest tests pass, including keyboard completion of stage 10 through both split/rejoin cycles and the end-of-campaign UI.
- Ruff lint and format checks pass.
- Offscreen screenshots of stage 10 were inspected at 1160 × 800 and the minimum 900 × 740 window size. The complete board, upright block, descriptions and controls fit.
- The wheel builds successfully and contains all ten validated stage JSON resources.
