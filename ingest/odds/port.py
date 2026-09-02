"""OddsProvider port. Capture talks to this, never to a vendor SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ingest.odds.types import Fixture, FixtureResult, MarketRef, Quote


class OddsProvider(Protocol):
    """Narrow vendor-agnostic surface for fixture discovery and odds reads.

    Implementations own batching, rate limits, and credit accounting. The
    pipeline must not encode a particular vendor's request shape.
    """

    def list_fixtures(
        self,
        league: str,
        season_year: int,
        *,
        start_after: datetime,
        start_before: datetime,
    ) -> list[Fixture]:
        """Upcoming fixtures in ``league`` whose start falls in the window."""

    def list_markets(
        self,
        vendor_fixture_id: str,
        sportsbooks: list[str],
    ) -> list[MarketRef]:
        """Markets each sportsbook currently offers on the fixture.

        An empty list is a normal state (the book has not opened markets yet),
        not an error.
        """

    def get_odds(
        self,
        vendor_fixture_ids: list[str],
        sportsbooks: list[str],
        markets: list[str],
    ) -> list[Quote]:
        """Current quotes for the given fixtures, books, and market keys."""

    def get_results(
        self,
        vendor_fixture_ids: list[str],
    ) -> list[FixtureResult]:
        """Scores / completion state for the given fixtures."""
