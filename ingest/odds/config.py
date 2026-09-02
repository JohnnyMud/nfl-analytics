"""Capture-cycle configuration. Values come from env; cadence consumes them."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from ingest.odds.cadence import DEFAULT_INTERVALS, CadenceIntervals

_DEFAULT_VENDOR = "the-odds-api"
_DEFAULT_SPORTSBOOKS = "draftkings,fanduel,betmgm"
_DEFAULT_MARKETS = "h2h,spreads,totals"
_DEFAULT_LOCK_KEY = 814_001_004
_DEFAULT_MONTHLY_CREDIT_BUDGET = 500


class CaptureConfig(BaseModel):
    """Intervals, window, books, and markets. No secrets."""

    model_config = ConfigDict(frozen=True)

    vendor: str = _DEFAULT_VENDOR
    sportsbooks: list[str] = Field(default_factory=lambda: _csv(_DEFAULT_SPORTSBOOKS))
    markets: list[str] = Field(default_factory=lambda: _csv(_DEFAULT_MARKETS))
    capture_window: timedelta = timedelta(days=7)
    slate_ttl: timedelta = timedelta(hours=1)
    tick_interval: timedelta = timedelta(seconds=60)
    intervals: CadenceIntervals = DEFAULT_INTERVALS
    coarsen_budget_fraction: float = 0.20
    abandon_after: timedelta = timedelta(seconds=900)
    league: str = "nfl"
    season_year: int = Field(default_factory=lambda: datetime.now(UTC).year)
    monthly_credit_budget: int = _DEFAULT_MONTHLY_CREDIT_BUDGET
    advisory_lock_key: int = _DEFAULT_LOCK_KEY

    @classmethod
    def from_env(cls) -> CaptureConfig:
        """Load from ``ODDS_*`` environment variables. Missing keys use defaults."""
        return cls(
            vendor=os.environ.get("ODDS_VENDOR", _DEFAULT_VENDOR),
            sportsbooks=_csv(os.environ.get("ODDS_SPORTSBOOKS", _DEFAULT_SPORTSBOOKS)),
            markets=_csv(os.environ.get("ODDS_MARKETS", _DEFAULT_MARKETS)),
            capture_window=timedelta(
                days=_int("ODDS_CAPTURE_WINDOW_DAYS", 7),
            ),
            slate_ttl=timedelta(seconds=_int("ODDS_SLATE_TTL_SECONDS", 3600)),
            tick_interval=timedelta(seconds=_int("ODDS_TICK_INTERVAL_SECONDS", 60)),
            intervals=CadenceIntervals(
                coarse=timedelta(seconds=_int("ODDS_COARSE_INTERVAL_SECONDS", 10800)),
                medium=timedelta(seconds=_int("ODDS_MEDIUM_INTERVAL_SECONDS", 900)),
                fine=timedelta(seconds=_int("ODDS_FINE_INTERVAL_SECONDS", 120)),
            ),
            coarsen_budget_fraction=_float("ODDS_COARSEN_BUDGET_FRACTION", 0.20),
            abandon_after=timedelta(seconds=_int("ODDS_ABANDON_AFTER_SECONDS", 900)),
            league=os.environ.get("ODDS_LEAGUE", "nfl"),
            season_year=_int("ODDS_SEASON_YEAR", datetime.now(UTC).year),
            monthly_credit_budget=_int(
                "ODDS_MONTHLY_CREDIT_BUDGET", _DEFAULT_MONTHLY_CREDIT_BUDGET
            ),
            advisory_lock_key=_int("ODDS_ADVISORY_LOCK_KEY", _DEFAULT_LOCK_KEY),
        )


def _csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)
