# Gameplay conventions

These decisions resolve details left unspecified in the assignment. Manual play and any future solver use the same engine.

- Coordinates are zero-based `(row, column)`. A normal block is anchored at its top/left cell.
- Falling off the board, onto unsupported void or onto fragile terrain while standing ends the game. Restart restores the entire initial state. The engine reports a lost outcome; future solvers should omit it from successors.
- A unit cube can rest on fragile tiles because it weighs half as much as the complete standing block.
- Soft switches trigger on a change from unpressed to pressed. Heavy/split switches are pressed only by an intact standing block. Becoming upright on a previously covered heavy switch therefore activates it.
- Several newly pressed switches execute in ascending ID order. Effects execute before checking final bridge support. A switch can open a bridge under the other half of the block; closing a bridge under either cube causes a loss.
- A permanent bridge effect means idempotent `set open/closed`, not a global lock against other switches. Level authors should avoid conflicting effects unless that interaction is intentional.
- Split switches teleport A and B to distinct fixed positions. A becomes active. Switches at spawn positions do not activate during teleport; final support is still checked.
- Split cubes merge automatically after a directional move leaves them on adjacent cells, creating a lying block. Adjacent teleport spawns remain split until the next directional move. Swapping never merges or activates switches.
- Moving a cube onto the other cube is invalid and does not consume a move. A legal swap is counted separately from rolls.
- A lying block can cover the goal safely. Only an intact standing block wins; a unit cube on the goal does not win.
- Levels must have one start and one goal, unique switch/bridge IDs, nonoverlapping bridge cells, and no overlapping switches. Bridges replace void cells. Switches occupy ordinary floor (including the start), not goal, fragile or bridge cells.
- Initial support is validated. A switch beneath the start is considered already pressed and does not fire automatically.
