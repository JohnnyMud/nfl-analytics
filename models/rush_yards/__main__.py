"""CLI placeholder. Does not load nflverse or fit 2016–2025.

The trainer is in-memory: call ``walk_forward`` with labeled rows already
built at each game's kickoff. A future DB run can assemble those rows
without changing this default entrypoint.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m models.rush_yards",
        description=(
            "In-memory rush yards trainer. Does not connect to Postgres or "
            "run a 2016-2025 fit."
        ),
    )
    parser.parse_args(argv)
    sys.stdout.write(
        "models.rush_yards: no-op. Use walk_forward() on in-memory labeled "
        "rows. This CLI will not fit 2016-2025 or load nflverse.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
