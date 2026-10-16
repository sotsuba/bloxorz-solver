from dataclasses import dataclass 
from typing import Protocol, Hashable, Iterable 

@dataclass(frozen=True)
class Transition:
    action: str 
    next_state: Hashable 
    cost: float = 1.0

class SearchProblem(Protocol):
    def is_goal(self, state: Hashable) -> bool:
        ...

    def get_successors(self, state: Hashable) -> Iterable[Transition]:
        ...