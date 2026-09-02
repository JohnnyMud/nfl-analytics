"""Kickoff-relative snapshot cadence. Pure: no clock, DB, or network."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Tier(StrEnum):
    coarse = "coarse"
    medium = "medium"
    fine = "fine"
    none = "none"


class CadenceIntervals(BaseModel):
    """Per-tier poll spacing. Owned by config; cadence only consumes it."""

    model_config = ConfigDict(frozen=True)

    coarse: timedelta
    medium: timedelta
    fine: timedelta


DEFAULT_INTERVALS = CadenceIntervals(
    coarse=timedelta(hours=3),
    medium=timedelta(minutes=15),
    fine=timedelta(minutes=2),
)

_FINE_BEFORE_KICKOFF = timedelta(minutes=30)
_MEDIUM_BEFORE_KICKOFF = timedelta(hours=12)
_COARSEN: dict[Tier, Tier] = {
    Tier.fine: Tier.medium,
    Tier.medium: Tier.coarse,
    Tier.coarse: Tier.none,
    Tier.none: Tier.none,
}


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def determine_tier(kickoff_at: datetime, now: datetime) -> Tier:
    """Week 1 three-tier window relative to ``kickoff_at``.

    opening → T-12h = coarse, T-12h → T-30m = medium, T-30m → kickoff = fine,
    otherwise none. Comparisons are UTC-aware; the caller injects ``now``.
    """
    kickoff_at = _require_aware(kickoff_at)
    now = _require_aware(now)
    if now >= kickoff_at:
        return Tier.none
    until_kickoff = kickoff_at - now
    if until_kickoff <= _FINE_BEFORE_KICKOFF:
        return Tier.fine
    if until_kickoff <= _MEDIUM_BEFORE_KICKOFF:
        return Tier.medium
    return Tier.coarse


def poll_interval(
    tier: Tier, intervals: CadenceIntervals = DEFAULT_INTERVALS
) -> timedelta:
    """Spacing for a pollable tier. ``none`` is not pollable."""
    if tier is Tier.none:
        raise ValueError("tier none has no poll interval")
    if tier is Tier.coarse:
        return intervals.coarse
    if tier is Tier.medium:
        return intervals.medium
    return intervals.fine


def poll_due(
    last_poll_at: datetime | None,
    tier: Tier,
    now: datetime,
    intervals: CadenceIntervals = DEFAULT_INTERVALS,
) -> bool:
    """True when no prior poll exists or the tier interval has elapsed."""
    now = _require_aware(now)
    if last_poll_at is not None:
        last_poll_at = _require_aware(last_poll_at)
    if tier is Tier.none:
        return False
    if last_poll_at is None:
        return True
    return now - last_poll_at >= poll_interval(tier, intervals)


def coarsen(tier: Tier) -> Tier:
    """Degrade one step: fine → medium → coarse → none."""
    return _COARSEN[tier]
