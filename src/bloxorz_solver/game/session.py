"""Manual game lifecycle without any GUI dependency."""

from dataclasses import dataclass, field

from bloxorz_solver.game.rules import initial_state, transition
from bloxorz_solver.game.state import (
    Action,
    GameState,
    Level,
    Outcome,
    StringEnum,
    TransitionResult,
)
from bloxorz_solver.game.validation import validate_level


class SessionStatus(StringEnum):
    PLAYING = "playing"
    WON = "won"
    LOST = "lost"


@dataclass
class GameSession:
    """Own the current state, terminal outcome and player counters."""

    level: Level
    state: GameState = field(init=False)
    status: SessionStatus = field(init=False)
    roll_count: int = field(init=False, default=0)
    swap_count: int = field(init=False, default=0)
    last_result: TransitionResult | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        validate_level(self.level)
        self.restart()

    @property
    def action_count(self) -> int:
        """Count rolls and control swaps separately from search state."""
        return self.roll_count + self.swap_count

    def restart(self) -> None:
        """Reset the block, bridges, outcome and counters together."""
        self.state = initial_state(self.level)
        self.status = SessionStatus.PLAYING
        self.roll_count = self.swap_count = 0
        self.last_result = None

    def apply_action(self, action: Action) -> TransitionResult | None:
        """Apply input while playing; terminal sessions require a restart."""
        if self.status is not SessionStatus.PLAYING:
            return None
        result = transition(self.level, self.state, action)
        self.last_result = result
        if result.outcome is Outcome.INVALID:
            return result
        self.state = result.next_state
        if action is Action.SWAP_ACTIVE_CUBE:
            self.swap_count += 1
        else:
            self.roll_count += 1
        if result.outcome is Outcome.WON:
            self.status = SessionStatus.WON
        elif result.outcome is Outcome.LOST:
            self.status = SessionStatus.LOST
        return result
