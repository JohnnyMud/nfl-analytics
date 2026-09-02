"""Offline cadence-engine tests. No DB, no network, no system clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ingest.odds.cadence import (
    DEFAULT_INTERVALS,
    CadenceIntervals,
    Tier,
    coarsen,
    determine_tier,
    poll_due,
    poll_interval,
)

KICKOFF = datetime(2026, 9, 6, 20, 20, tzinfo=UTC)


def _at(delta: timedelta) -> datetime:
    return KICKOFF + delta


def test_tier_t_minus_13h_is_coarse() -> None:
    assert determine_tier(KICKOFF, _at(-timedelta(hours=13))) is Tier.coarse


def test_tier_t_minus_11h_is_medium() -> None:
    assert determine_tier(KICKOFF, _at(-timedelta(hours=11))) is Tier.medium


def test_tier_t_minus_29m_is_fine() -> None:
    assert determine_tier(KICKOFF, _at(-timedelta(minutes=29))) is Tier.fine


def test_tier_t_plus_10m_is_none() -> None:
    assert determine_tier(KICKOFF, _at(timedelta(minutes=10))) is Tier.none


def test_tier_boundaries_inclusive_of_window_start() -> None:
    assert determine_tier(KICKOFF, _at(-timedelta(hours=12))) is Tier.medium
    assert determine_tier(KICKOFF, _at(-timedelta(minutes=30))) is Tier.fine
    assert determine_tier(KICKOFF, KICKOFF) is Tier.none


def test_poll_due_false_within_interval() -> None:
    now = KICKOFF - timedelta(hours=6)
    last = now - timedelta(hours=2)
    assert poll_due(last, Tier.coarse, now) is False


def test_poll_due_true_after_interval() -> None:
    now = KICKOFF - timedelta(hours=6)
    last = now - timedelta(hours=3)
    assert poll_due(last, Tier.coarse, now) is True


def test_poll_due_true_when_no_prior_poll() -> None:
    now = KICKOFF - timedelta(hours=6)
    assert poll_due(None, Tier.coarse, now) is True


def test_poll_due_false_for_none_even_without_prior_poll() -> None:
    assert poll_due(None, Tier.none, KICKOFF) is False


def test_poll_interval_from_config() -> None:
    custom = CadenceIntervals(
        coarse=timedelta(hours=4),
        medium=timedelta(minutes=20),
        fine=timedelta(minutes=1),
    )
    assert poll_interval(Tier.coarse, custom) == timedelta(hours=4)
    assert poll_interval(Tier.medium, custom) == timedelta(minutes=20)
    assert poll_interval(Tier.fine, custom) == timedelta(minutes=1)


def test_poll_interval_defaults() -> None:
    assert poll_interval(Tier.coarse) == DEFAULT_INTERVALS.coarse
    assert poll_interval(Tier.medium) == DEFAULT_INTERVALS.medium
    assert poll_interval(Tier.fine) == DEFAULT_INTERVALS.fine


def test_poll_interval_none_raises() -> None:
    with pytest.raises(ValueError, match="none"):
        poll_interval(Tier.none)


def test_coarsen_ladder() -> None:
    assert coarsen(Tier.fine) is Tier.medium
    assert coarsen(Tier.medium) is Tier.coarse
    assert coarsen(Tier.coarse) is Tier.none
    assert coarsen(Tier.none) is Tier.none


def test_naive_datetime_rejected() -> None:
    naive = datetime(2026, 9, 6, 20, 20)
    aware = KICKOFF
    with pytest.raises(ValueError, match="timezone-aware"):
        determine_tier(naive, aware)
    with pytest.raises(ValueError, match="timezone-aware"):
        determine_tier(aware, naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        poll_due(naive, Tier.coarse, aware)
    with pytest.raises(ValueError, match="timezone-aware"):
        poll_due(aware, Tier.coarse, naive)
