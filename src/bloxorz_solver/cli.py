"""Command-line entry point; importing game and solver modules needs no display."""

import argparse
from pathlib import Path

from bloxorz_solver.levels.loader import LevelFormatError, builtin_levels, load_level


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play Bloxorz using Pygame.")
    parser.add_argument("--level", type=Path, help="Start with an external JSON level")
    args = parser.parse_args(argv)
    levels = list(builtin_levels())
    if args.level:
        try:
            levels.insert(0, load_level(args.level))
        except LevelFormatError as exc:
            parser.error(str(exc))
    from bloxorz_solver.ui.app import GameApp

    return GameApp(levels).run()
