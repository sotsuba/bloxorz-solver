"""Bloxorz game and search algorithms."""


def main(argv: list[str] | None = None) -> int:
    """Launch the Pygame application without importing it for library users."""
    from bloxorz_solver.cli import main as run

    return run(argv)
