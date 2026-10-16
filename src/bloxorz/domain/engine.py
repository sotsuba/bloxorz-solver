"""Pure, deterministic Bloxorz movement and mechanism rules."""

from bloxorz.domain.models import (
    Action,
    BlockState,
    BridgeEffect,
    EffectMode,
    EventType,
    GameEvent,
    GameState,
    Level,
    NormalBlock,
    Orientation,
    Outcome,
    Position,
    SplitBlock,
    Switch,
    SwitchKind,
    TransitionResult,
)

S, H, V = Orientation.STANDING, Orientation.HORIZONTAL, Orientation.VERTICAL
ROLLS = (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT)
DIRECTIONS = {Action.UP: (-1, 0), Action.DOWN: (1, 0), Action.LEFT: (0, -1), Action.RIGHT: (0, 1)}
ROLL_TABLE = {
    S: {
        Action.UP: (-2, 0, V),
        Action.DOWN: (1, 0, V),
        Action.LEFT: (0, -2, H),
        Action.RIGHT: (0, 1, H),
    },
    H: {
        Action.UP: (-1, 0, H),
        Action.DOWN: (1, 0, H),
        Action.LEFT: (0, -1, S),
        Action.RIGHT: (0, 2, S),
    },
    V: {
        Action.UP: (-1, 0, S),
        Action.DOWN: (2, 0, S),
        Action.LEFT: (0, -1, V),
        Action.RIGHT: (0, 1, V),
    },
}


def initial_state(level: Level) -> GameState:
    """Restore the standing block and the level's initial bridge configuration."""
    mask = sum(1 << level.bridge_indices[b.id] for b in level.bridges if b.initially_open)
    return GameState(NormalBlock(*level.start), mask)


def occupied_cells(block: BlockState) -> tuple[Position, ...]:
    """Return every cell supporting the complete block or the two cubes."""
    if isinstance(block, SplitBlock):
        return block.cube_a, block.cube_b
    anchor = Position(block.row, block.col)
    if block.orientation is H:
        return anchor, Position(block.row, block.col + 1)
    if block.orientation is V:
        return anchor, Position(block.row + 1, block.col)
    return (anchor,)


def is_goal(level: Level, state: GameState) -> bool:
    """Only an intact upright block can complete a stage."""
    block = state.block
    return (
        isinstance(block, NormalBlock)
        and block.orientation is S
        and (block.row, block.col) == level.goal
    )


def bridge_is_open(level: Level, state: GameState, bridge_id: str) -> bool:
    """Read one bridge's passability from the state's mask."""
    return bool(state.bridge_mask & (1 << level.bridge_indices[bridge_id]))


def legal_actions(level: Level, state: GameState) -> tuple[Action, ...]:
    """Exclude invalid and losing actions for future search adapters."""
    actions = (*ROLLS, Action.SWAP_ACTIVE_CUBE) if isinstance(state.block, SplitBlock) else ROLLS
    return tuple(
        action
        for action in actions
        if transition(level, state, action).outcome in (Outcome.MOVED, Outcome.WON)
    )


def transition(level: Level, state: GameState, action: Action) -> TransitionResult:
    """Apply one action without modifying inputs, including explicit fall outcomes."""
    if is_goal(level, state):
        return TransitionResult(state, Outcome.INVALID, reason="stage_finished")
    block = _move_block(state.block, action)
    if block is None:
        return TransitionResult(state, Outcome.INVALID, reason="invalid_action")
    if action is Action.SWAP_ACTIVE_CUBE:
        return TransitionResult(GameState(block, state.bridge_mask), Outcome.MOVED)
    if any(not level.contains(cell) for cell in occupied_cells(block)):
        return TransitionResult(
            GameState(block, state.bridge_mask), Outcome.LOST, reason="out_of_bounds"
        )
    block, events = _merge(block)
    next_state, switch_events = _activate_switches(level, state, block)
    events += switch_events
    reason = support_failure(level, next_state)
    if reason:
        return TransitionResult(next_state, Outcome.LOST, events, reason)
    outcome = Outcome.WON if is_goal(level, next_state) else Outcome.MOVED
    return TransitionResult(next_state, outcome, events)


def support_failure(level: Level, state: GameState) -> str:
    """Describe unsupported terrain, or return an empty string for safe support."""
    for cell in occupied_cells(state.block):
        reason = _cell_support_failure(level, state, cell)
        if reason:
            return reason
    return ""


def supported_cells(level: Level, state: GameState) -> tuple[Position, ...]:
    """Expose actual block support without duplicating terrain rules in the renderer."""
    return tuple(
        cell
        for cell in occupied_cells(state.block)
        if not _cell_support_failure(level, state, cell)
    )


def _cell_support_failure(level: Level, state: GameState, cell: Position) -> str:
    """Evaluate one contact cell using the current bridge configuration."""
    if not level.contains(cell):
        return "out_of_bounds"
    bridge_id = level.bridge_at.get(cell)
    if bridge_id and not bridge_is_open(level, state, bridge_id):
        return "unsupported"
    tile = level.grid[cell.row][cell.col]
    if tile == "#" and bridge_id is None:
        return "unsupported"
    if tile == "F" and isinstance(state.block, NormalBlock) and state.block.orientation is S:
        return "fragile"
    return ""


def _move_block(block: BlockState, action: Action) -> BlockState | None:
    """Roll an intact block or translate just the active cube."""
    if action is Action.SWAP_ACTIVE_CUBE:
        return (
            SplitBlock(block.cube_a, block.cube_b, 1 - block.active_cube)
            if isinstance(block, SplitBlock)
            else None
        )
    if isinstance(block, NormalBlock):
        dr, dc, orientation = ROLL_TABLE[block.orientation][action]
        return NormalBlock(block.row + dr, block.col + dc, orientation)
    cubes = [block.cube_a, block.cube_b]
    dr, dc = DIRECTIONS[action]
    active = cubes[block.active_cube]
    cubes[block.active_cube] = Position(active.row + dr, active.col + dc)
    if cubes[0] == cubes[1]:
        return None
    return SplitBlock(*cubes, active_cube=block.active_cube)


def _merge(block: BlockState) -> tuple[BlockState, tuple[GameEvent, ...]]:
    """Rejoin adjacent unit cubes after a directional movement."""
    if isinstance(block, NormalBlock):
        return block, ()
    a, b = block.cube_a, block.cube_b
    if abs(a.row - b.row) + abs(a.col - b.col) != 1:
        return block, ()
    orientation = H if a.row == b.row else V
    merged = NormalBlock(min(a.row, b.row), min(a.col, b.col), orientation)
    return merged, (GameEvent(EventType.BLOCK_MERGED),)


def _is_pressed(switch: Switch, block: BlockState) -> bool:
    """Evaluate the switch's orientation-sensitive press condition."""
    if switch.kind is SwitchKind.SOFT:
        return switch.position in occupied_cells(block)
    return (
        isinstance(block, NormalBlock)
        and block.orientation is S
        and (block.row, block.col) == switch.position
    )


def _activate_switches(
    level: Level, previous: GameState, block: BlockState
) -> tuple[GameState, tuple[GameEvent, ...]]:
    """Apply newly pressed switches once, in deterministic ID order."""
    pressed = [
        s for s in level.switches if _is_pressed(s, block) and not _is_pressed(s, previous.block)
    ]
    mask = previous.bridge_mask
    events = []
    for switch in sorted(pressed, key=lambda s: s.id):
        events.append(GameEvent(EventType.SWITCH_TRIGGERED, switch.id))
        if switch.bridge_effect:
            mask, bridge_events = _apply_effect(level, mask, switch.bridge_effect)
            events.extend(bridge_events)
        if switch.kind is SwitchKind.SPLIT:
            block = SplitBlock(*switch.spawn_positions)
            events.append(GameEvent(EventType.BLOCK_SPLIT, switch.id))
    return GameState(block, mask), tuple(events)


def _apply_effect(
    level: Level, mask: int, effect: BridgeEffect
) -> tuple[int, tuple[GameEvent, ...]]:
    """Toggle or idempotently set each linked bridge."""
    events = []
    for bridge_id in effect.targets:
        bit = 1 << level.bridge_indices[bridge_id]
        was_open = bool(mask & bit)
        is_open = not was_open if effect.mode is EffectMode.TOGGLE else effect.open
        mask = mask | bit if is_open else mask & ~bit
        if was_open != is_open:
            kind = EventType.BRIDGE_OPENED if is_open else EventType.BRIDGE_CLOSED
            events.append(GameEvent(kind, bridge_id))
    return mask, tuple(events)
