"""Search metrics must not take ownership of a caller's tracing session."""

import tracemalloc

import pytest

from bloxorz_solver.levels.loader import builtin_levels
from bloxorz_solver.solvers.base import BaseSolver
from bloxorz_solver.solvers.problem import BloxorzProblem


class MetricsProbe(BaseSolver):
    def __init__(self, problem, *, fail):
        super().__init__(problem)
        self.fail = fail

    def _search(self, initial_state):
        assert tracemalloc.is_tracing()
        if self.fail:
            raise RuntimeError("search failed")
        return ["right"] * 4, 4


@pytest.mark.parametrize("already_tracing", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_solve_preserves_tracing_ownership(already_tracing, fail):
    original_tracing = tracemalloc.is_tracing()
    problem = BloxorzProblem(builtin_levels()[0])
    solver = MetricsProbe(problem, fail=fail)
    try:
        tracemalloc.stop()
        if already_tracing:
            tracemalloc.start()
            marker = bytearray(1024)
            traceback = tracemalloc.get_object_traceback(marker)
            allocation = bytearray(1_000_000)
            del allocation
            _, previous_peak = tracemalloc.get_traced_memory()
        if fail:
            with pytest.raises(RuntimeError, match="search failed"):
                solver.solve(problem.initial_state)
        else:
            result = solver.solve(problem.initial_state)
            assert result.path == ["right"] * 4
            assert result.solution_length == result.expanded_nodes == 4
            assert result.search_time >= 0
            assert result.peak_memory > 0
            if already_tracing:
                assert result.peak_memory >= previous_peak
        assert tracemalloc.is_tracing() is already_tracing
        if already_tracing:
            assert tracemalloc.get_object_traceback(marker) == traceback
            assert tracemalloc.get_traced_memory()[1] >= previous_peak
    finally:
        if original_tracing:
            tracemalloc.start()
        else:
            tracemalloc.stop()
