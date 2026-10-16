"""Validate static level invariants before allowing a game session."""

from bloxorz.domain.models import EffectMode, Level, Switch, SwitchKind


def validate_level(level: Level) -> None:
    """Reject malformed terrain, mechanism references and spawn placements."""
    if not level.grid or not level.grid[0]:
        raise ValueError("grid must not be empty")
    if any(len(row) != level.width for row in level.grid):
        raise ValueError("grid rows must have equal width")
    if any(char not in "#.SGF" for row in level.grid for char in row):
        raise ValueError("grid contains an unknown tile; use # . S G F")
    for marker, position in (("S", level.start), ("G", level.goal)):
        if sum(row.count(marker) for row in level.grid) != 1:
            raise ValueError(f"grid must contain exactly one {marker}")
        if not level.contains(position) or level.grid[position.row][position.col] != marker:
            raise ValueError(f"{marker} position does not match the grid")
    ids = [item.id for item in (*level.bridges, *level.switches)]
    if len(ids) != len(set(ids)):
        raise ValueError("bridge and switch IDs must be unique")
    _validate_bridges(level)
    _validate_switches(level)


def _validate_bridges(level: Level) -> None:
    """Require nonoverlapping bridge cells on the void layer."""
    occupied = set()
    for bridge in level.bridges:
        if not bridge.cells:
            raise ValueError(f"bridge {bridge.id}: cells must not be empty")
        for cell in bridge.cells:
            if not level.contains(cell):
                raise ValueError(f"bridge {bridge.id}: cell {cell} is outside the board")
            if level.grid[cell.row][cell.col] != "#":
                raise ValueError(f"bridge {bridge.id}: cells must cover void tiles")
            if cell in occupied:
                raise ValueError(f"bridge {bridge.id}: overlapping or duplicate cell {cell}")
            occupied.add(cell)


def _validate_switches(level: Level) -> None:
    """Check switch terrain, bridge effects and split-specific invariants."""
    occupied = set()
    for switch in level.switches:
        pos = switch.position
        if not level.contains(pos) or level.grid[pos.row][pos.col] not in ".S":
            raise ValueError(f"switch {switch.id}: position must be an ordinary floor tile")
        if pos in occupied:
            raise ValueError(f"switch {switch.id}: overlapping switch position")
        occupied.add(pos)
        if switch.bridge_effect:
            _validate_effect(level, switch)
        elif switch.kind is not SwitchKind.SPLIT:
            raise ValueError(f"switch {switch.id}: bridge_effect is required")
        if switch.kind is SwitchKind.SPLIT:
            _validate_spawns(level, switch)
        elif switch.spawn_positions:
            raise ValueError(f"switch {switch.id}: only split switches have spawn positions")


def _validate_effect(level: Level, switch: Switch) -> None:
    """Require real bridge targets and an explicit Boolean for set effects."""
    effect = switch.bridge_effect
    if not effect.targets or len(set(effect.targets)) != len(effect.targets):
        raise ValueError(f"switch {switch.id}: targets must be nonempty and unique")
    if any(target not in level.bridge_indices for target in effect.targets):
        raise ValueError(f"switch {switch.id}: unknown bridge target")
    if effect.mode is EffectMode.SET and not isinstance(effect.open, bool):
        raise ValueError(f"switch {switch.id}: set effect needs a Boolean open value")
    if effect.mode is EffectMode.TOGGLE and effect.open is not None:
        raise ValueError(f"switch {switch.id}: toggle effect must not specify open")


def _validate_spawns(level: Level, switch: Switch) -> None:
    """Allow distinct supported spawn cells, including dynamic bridge cells."""
    if len(switch.spawn_positions) != 2 or len(set(switch.spawn_positions)) != 2:
        raise ValueError(f"switch {switch.id}: need exactly two distinct spawn positions")
    for pos in switch.spawn_positions:
        if not level.contains(pos):
            raise ValueError(f"switch {switch.id}: spawn position outside the board")
        if level.grid[pos.row][pos.col] == "#" and pos not in level.bridge_at:
            raise ValueError(f"switch {switch.id}: spawn position is unsupported void")
