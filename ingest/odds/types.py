"""Normalized odds types. No vendor-specific field names."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, NewType

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

SnapshotId = NewType("SnapshotId", int)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must be timezone-aware")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]


class _VendorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: str
    raw: dict[str, Any]


class Fixture(_VendorEnvelope):
    """A vendor fixture (game) discovered before our own game dimension exists."""

    vendor_fixture_id: str
    league: str
    season_year: int
    season_type: str
    vendor_season_week: str | None
    start_date: AwareDatetime
    status: str
    home_team_vendor_id: str
    away_team_vendor_id: str
    home_abbr: str | None
    away_abbr: str | None
    venue_neutral: bool | None


class MarketRef(_VendorEnvelope):
    """A market a sportsbook offered on a fixture, as discovered from the vendor."""

    vendor_fixture_id: str
    sportsbook: str
    market_id: str
    market_name: str


class Quote(_VendorEnvelope):
    """One sportsbook price for one selection at the moment of the vendor response."""

    vendor_odds_id: str
    vendor_fixture_id: str
    sportsbook: str
    market_id: str
    selection: str
    selection_line: str | None
    points: Decimal | None
    price_american: int
    price_decimal: Decimal
    is_main: bool
    vendor_player_id: str | None
    vendor_timestamp: AwareDatetime | None
    availability: str = Field(default="open")


class FixtureResult(_VendorEnvelope):
    """Final (or in-progress) score for a vendor fixture."""

    vendor_fixture_id: str
    completed: bool
    home_score: int | None
    away_score: int | None
    vendor_timestamp: AwareDatetime | None


class SnapshotScope(BaseModel):
    """Requested capture scope. Stored on odds_snapshot; never inferred from quotes."""

    model_config = ConfigDict(extra="forbid")

    vendor_fixture_ids: list[str]
    sportsbooks: list[str]
    markets: list[str]


class WriteStats(BaseModel):
    """Counts from write_quotes. close_snapshot persists these onto the snapshot row."""

    model_config = ConfigDict(extra="forbid")

    quotes_seen: int
    quotes_written: int
    max_vendor_ts: AwareDatetime | None
    requests_made: int = 0
