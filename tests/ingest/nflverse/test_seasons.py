"""Season-range helper: nightly default, inclusive bounds, explicit env pair."""

from __future__ import annotations

import pytest

from ingest.nflverse.seasons import resolve_seasons, seasons_from_env


def test_resolve_seasons_defaults_to_current() -> None:
    assert resolve_seasons(None, None, current_season=2026) == (2026,)


def test_resolve_seasons_uses_caller_current_season() -> None:
    assert resolve_seasons(None, None, current_season=1999) == (1999,)


def test_resolve_seasons_inclusive_range() -> None:
    assert resolve_seasons(2012, 2015, current_season=2026) == (2012, 2013, 2014, 2015)


def test_resolve_seasons_single_year() -> None:
    assert resolve_seasons(2018, 2018, current_season=2026) == (2018,)


def test_resolve_seasons_start_after_end_raises() -> None:
    with pytest.raises(ValueError, match="after end season"):
        resolve_seasons(2020, 2018, current_season=2026)


def test_resolve_seasons_partial_pair_raises() -> None:
    with pytest.raises(ValueError, match="both be provided"):
        resolve_seasons(2012, None, current_season=2026)
    with pytest.raises(ValueError, match="both be provided"):
        resolve_seasons(None, 2015, current_season=2026)


def test_seasons_from_env_missing_both_is_current() -> None:
    assert seasons_from_env({}, current_season=2026) == (2026,)


def test_seasons_from_env_reads_inclusive_range() -> None:
    assert seasons_from_env(
        {"NFLVERSE_SEASON_START": "2012", "NFLVERSE_SEASON_END": "2014"},
        current_season=2026,
    ) == (2012, 2013, 2014)


def test_seasons_from_env_partial_pair_raises() -> None:
    with pytest.raises(ValueError, match="must both be set"):
        seasons_from_env({"NFLVERSE_SEASON_START": "2012"}, current_season=2026)
    with pytest.raises(ValueError, match="must both be set"):
        seasons_from_env({"NFLVERSE_SEASON_END": "2014"}, current_season=2026)


def test_seasons_from_env_start_after_end_raises() -> None:
    with pytest.raises(ValueError, match="after end season"):
        seasons_from_env(
            {"NFLVERSE_SEASON_START": "2020", "NFLVERSE_SEASON_END": "2018"},
            current_season=2026,
        )
