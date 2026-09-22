"""Resolve the nflverse season range for nightly ingest and historical backfill.

Callers pass ``current_season`` in. This module does not call ``now()`` or
``nfl.get_current_season()``.
"""

from __future__ import annotations

from collections.abc import Mapping

_START_ENV = "NFLVERSE_SEASON_START"
_END_ENV = "NFLVERSE_SEASON_END"


def resolve_seasons(
    start: int | None,
    end: int | None,
    *,
    current_season: int,
) -> tuple[int, ...]:
    """Return an inclusive season range, or the current season when both ends are omitted."""
    if start is None and end is None:
        return (int(current_season),)
    if start is None or end is None:
        raise ValueError("start and end must both be provided or both omitted")
    if start > end:
        raise ValueError(f"start season {start} is after end season {end}")
    return tuple(range(int(start), int(end) + 1))


def seasons_from_env(
    environ: Mapping[str, str],
    *,
    current_season: int,
) -> tuple[int, ...]:
    """Read ``NFLVERSE_SEASON_START`` / ``NFLVERSE_SEASON_END`` from ``environ``.

    Missing both keys keeps the nightly default (current season only). A
    partial pair is an error: a backfill range must be explicit.
    """
    start_raw = environ.get(_START_ENV)
    end_raw = environ.get(_END_ENV)
    if start_raw is None and end_raw is None:
        return resolve_seasons(None, None, current_season=current_season)
    if start_raw is None or end_raw is None:
        raise ValueError(f"{_START_ENV} and {_END_ENV} must both be set")
    return resolve_seasons(int(start_raw), int(end_raw), current_season=current_season)
