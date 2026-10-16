"""Immutable game values shared by the engine and interface."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from types import MappingProxyType
from typing import NamedTuple


class Position(NamedTuple):
    """A zero-based row and column."""

    row: int
    col: int


class Orientation(StrEnum):
    STANDING = "standing"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class Action(StrEnum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    SWAP_ACTIVE_CUBE = "swap"


class SwitchKind(StrEnum):
    SOFT = "soft"
    HEAVY = "heavy"
    SPLIT = "split"


class EffectMode(StrEnum):
    TOGGLE = "toggle"
    SET = "set"


class Outcome(StrEnum):
    MOVED = "moved"
    WON = "won"
    LOST = "lost"
    INVALID = "invalid"


class EventType(StrEnum):
    SWITCH_TRIGGERED = "switch_triggered"
    BRIDGE_OPENED = "bridge_opened"
    BRIDGE_CLOSED = "bridge_closed"
    BLOCK_SPLIT = "block_split"
    BLOCK_MERGED = "block_merged"


@dataclass(frozen=True, slots=True)
class NormalBlock:
    """An intact block anchored at its top/left occupied cell."""

    row: int
    col: int
    orientation: Orientation = Orientation.STANDING


@dataclass(frozen=True, slots=True)
class SplitBlock:
    """Stable cube identities and the currently controlled cube index."""

    cube_a: Position
    cube_b: Position
    active_cube: int = 0


BlockState = NormalBlock | SplitBlock


@dataclass(frozen=True, slots=True)
class GameState:
    block: BlockState
    bridge_mask: int = 0


@dataclass(frozen=True, slots=True)
class Bridge:
    id: str
    cells: tuple[Position, ...]
    initially_open: bool = False


@dataclass(frozen=True, slots=True)
class BridgeEffect:
    mode: EffectMode
    targets: tuple[str, ...]
    open: bool | None = None


@dataclass(frozen=True, slots=True)
class Switch:
    id: str
    position: Position
    kind: SwitchKind
    bridge_effect: BridgeEffect | None = None
    spawn_positions: tuple[Position, ...] = ()


@dataclass(frozen=True)
class Level:
    """Static terrain with immutable, lazily indexed mechanisms."""

    id: str
    name: str
    grid: tuple[str, ...]
    start: Position
    goal: Position
    bridges: tuple[Bridge, ...] = ()
    switches: tuple[Switch, ...] = ()
    description: str = ""

    @property
    def width(self) -> int:
        return len(self.grid[0])

    @property
    def height(self) -> int:
        return len(self.grid)

    def contains(self, position: Position) -> bool:
        """Return whether a coordinate lies inside this board."""
        return 0 <= position.row < self.height and 0 <= position.col < self.width

    @cached_property
    def bridge_indices(self) -> Mapping[str, int]:
        """Assign stable mask bits in ascending bridge ID order."""
        return MappingProxyType(
            {bridge.id: i for i, bridge in enumerate(sorted(self.bridges, key=lambda b: b.id))}
        )

    @cached_property
    def bridge_at(self) -> Mapping[Position, str]:
        """Index bridge cells without rescanning the board on each roll."""
        return MappingProxyType(
            {cell: bridge.id for bridge in self.bridges for cell in bridge.cells}
        )

    @cached_property
    def switch_at(self) -> Mapping[Position, Switch]:
        """Expose a read-only position-to-switch index for rendering."""
        return MappingProxyType({switch.position: switch for switch in self.switches})


@dataclass(frozen=True, slots=True)
class GameEvent:
    kind: EventType
    subject: str = ""


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """Outcome and attempted state; lost states must not be expanded by search."""

    next_state: GameState
    outcome: Outcome
    events: tuple[GameEvent, ...] = ()
    reason: str = ""
