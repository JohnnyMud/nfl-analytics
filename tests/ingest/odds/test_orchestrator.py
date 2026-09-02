"""Orchestrator integration tests. Stub provider, real writer, test Postgres."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event, Thread

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.odds.config import CaptureConfig
from ingest.odds.errors import RateBudgetExceeded
from ingest.odds.orchestrator import Orchestrator, TickStats
from ingest.odds.types import (
    Fixture,
    FixtureResult,
    MarketRef,
    Quote,
    SnapshotScope,
    WriteStats,
)
from ingest.odds.writer import close_snapshot, open_snapshot

VENDOR = "the-odds-api"
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
# T-13h → coarse. Fine-tier tests override start_date.
COARSE_KICKOFF = NOW + timedelta(hours=13)
FINE_KICKOFF = NOW + timedelta(minutes=20)


def make_config(**overrides: object) -> CaptureConfig:
    values: dict[str, object] = {
        "vendor": VENDOR,
        "sportsbooks": ["draftkings"],
        "markets": ["h2h"],
        "season_year": 2026,
        "advisory_lock_key": 814_001_004,
    }
    values.update(overrides)
    return CaptureConfig.model_validate(values)


def make_fixture(**overrides: object) -> Fixture:
    vendor_id = str(overrides.get("vendor_fixture_id", "fx-a"))
    values: dict[str, object] = {
        "vendor": VENDOR,
        "vendor_fixture_id": vendor_id,
        "league": "nfl",
        "season_year": 2026,
        "season_type": "regular",
        "vendor_season_week": None,
        "start_date": COARSE_KICKOFF,
        "status": "scheduled",
        "home_team_vendor_id": "Seattle Seahawks",
        "away_team_vendor_id": "New England Patriots",
        "home_abbr": "SEA",
        "away_abbr": "NE",
        "venue_neutral": False,
        "raw": {"id": vendor_id},
    }
    values.update(overrides)
    return Fixture.model_validate(values)


def make_quote(**overrides: object) -> Quote:
    vendor_id = str(overrides.get("vendor_fixture_id", "fx-a"))
    values: dict[str, object] = {
        "vendor": VENDOR,
        "vendor_odds_id": "odds-1",
        "vendor_fixture_id": vendor_id,
        "sportsbook": "draftkings",
        "market_id": "h2h",
        "selection": "Seattle Seahawks",
        "selection_line": None,
        "points": None,
        "price_american": -110,
        "price_decimal": Decimal("1.9091"),
        "is_main": True,
        "vendor_player_id": None,
        "vendor_timestamp": NOW,
        "availability": "open",
        "raw": {"quote": 1},
    }
    values.update(overrides)
    return Quote.model_validate(values)


class StubProvider:
    """In-memory OddsProvider. No network."""

    def __init__(
        self,
        fixtures: list[Fixture],
        quotes_by_id: dict[str, list[Quote]] | None = None,
        errors_by_id: dict[str, BaseException] | None = None,
        credits_remaining: int | None = None,
    ) -> None:
        self.fixtures = fixtures
        self.quotes_by_id = quotes_by_id or {}
        self.errors_by_id = errors_by_id or {}
        self.credits_remaining = credits_remaining
        self.list_calls = 0
        self.odds_calls: list[list[str]] = []

    def list_fixtures(
        self,
        league: str,
        season_year: int,
        *,
        start_after: datetime,
        start_before: datetime,
    ) -> list[Fixture]:
        self.list_calls += 1
        return [f for f in self.fixtures if start_after <= f.start_date <= start_before]

    def list_markets(
        self, vendor_fixture_id: str, sportsbooks: list[str]
    ) -> list[MarketRef]:
        return []

    def get_odds(
        self,
        vendor_fixture_ids: list[str],
        sportsbooks: list[str],
        markets: list[str],
    ) -> list[Quote]:
        self.odds_calls.append(list(vendor_fixture_ids))
        quotes: list[Quote] = []
        for fixture_id in vendor_fixture_ids:
            err = self.errors_by_id.get(fixture_id)
            if err is not None:
                raise err
            quotes.extend(self.quotes_by_id.get(fixture_id, []))
        return quotes

    def get_results(self, vendor_fixture_ids: list[str]) -> list[FixtureResult]:
        return []


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Engine]:
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                """
                TRUNCATE market.odds_market_state, market.odds_closing_line,
                         market.odds_observation, market.odds_snapshot,
                         market.vendor_fixture, market.market_catalog
                RESTART IDENTITY CASCADE
                """
            )
        )
    yield migrated_engine


def _observation_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM market.odds_observation")
            ).scalar_one()
        )


def _snapshot_rows(engine: Engine) -> list[tuple[int, str, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT snapshot_id, outcome, tier
                FROM market.odds_snapshot
                ORDER BY snapshot_id
                """
            )
        )
        return [(int(r.snapshot_id), str(r.outcome), str(r.tier)) for r in rows]


def _plant_ok_snapshot(
    engine: Engine, fixture_id: str, started_at: datetime, *, tier: str = "coarse"
) -> None:
    scope = SnapshotScope(
        vendor_fixture_ids=[fixture_id],
        sportsbooks=["draftkings"],
        markets=["h2h"],
    )
    snapshot_id = open_snapshot(engine, VENDOR, tier, scope, clock=lambda: started_at)
    close_snapshot(
        engine,
        snapshot_id,
        "ok",
        WriteStats(quotes_seen=0, quotes_written=0, max_vendor_ts=None),
        clock=lambda: started_at,
    )


def test_two_changed_quotes_close_ok(db: Engine) -> None:
    quotes = [
        make_quote(vendor_odds_id="odds-1", vendor_fixture_id="fx-a"),
        make_quote(vendor_odds_id="odds-2", vendor_fixture_id="fx-a"),
    ]
    provider = StubProvider(
        [make_fixture(vendor_fixture_id="fx-a")],
        quotes_by_id={"fx-a": quotes},
    )
    stats = Orchestrator(db, provider, make_config()).run_tick(NOW)

    assert stats.ok == 1
    assert stats.polls_issued == 1
    assert stats.observations_written == 2
    assert _observation_count(db) == 2
    outcomes = _snapshot_rows(db)
    assert len(outcomes) == 1
    assert outcomes[0][1] == "ok"


def test_fixture_not_due_skips_snapshot(db: Engine) -> None:
    _plant_ok_snapshot(db, "fx-a", NOW - timedelta(hours=1))
    provider = StubProvider(
        [make_fixture(vendor_fixture_id="fx-a")],
        quotes_by_id={"fx-a": [make_quote()]},
    )
    stats = Orchestrator(db, provider, make_config()).run_tick(NOW)

    assert stats.polls_issued == 0
    assert provider.odds_calls == []
    assert _snapshot_rows(db) == [(1, "ok", "coarse")]


def test_rate_limited_stops_tick_and_coarsens_next(db: Engine) -> None:
    fixtures = [
        make_fixture(vendor_fixture_id="fx-a", start_date=FINE_KICKOFF),
        make_fixture(vendor_fixture_id="fx-b", start_date=FINE_KICKOFF),
    ]
    provider = StubProvider(
        fixtures,
        quotes_by_id={
            "fx-b": [make_quote(vendor_fixture_id="fx-b", vendor_odds_id="odds-b")],
        },
        errors_by_id={"fx-a": RateBudgetExceeded("budget exhausted")},
    )
    orch = Orchestrator(db, provider, make_config())
    first = orch.run_tick(NOW)

    assert first.rate_limited == 1
    assert first.polls_issued == 1
    assert provider.odds_calls == [["fx-a", "fx-b"]]
    assert _snapshot_rows(db) == [(1, "rate_limited", "fine")]

    later = NOW + timedelta(minutes=15)
    provider.errors_by_id = {}
    provider.quotes_by_id["fx-a"] = [
        make_quote(vendor_fixture_id="fx-a", vendor_odds_id="odds-a")
    ]
    second = orch.run_tick(later)

    assert second.polls_issued >= 1
    rows = _snapshot_rows(db)
    assert any(outcome == "ok" and tier == "medium" for _sid, outcome, tier in rows)
    assert ["fx-b"] not in provider.odds_calls[:1]


def test_generic_exception_does_not_abort_other_fixtures(db: Engine) -> None:
    fixtures = [
        make_fixture(vendor_fixture_id="fx-a"),
        make_fixture(vendor_fixture_id="fx-b"),
    ]
    provider = StubProvider(
        fixtures,
        quotes_by_id={
            "fx-b": [
                make_quote(vendor_fixture_id="fx-b", vendor_odds_id="odds-b1"),
                make_quote(vendor_fixture_id="fx-b", vendor_odds_id="odds-b2"),
            ],
        },
        errors_by_id={"fx-a": RuntimeError("vendor exploded")},
    )
    stats = Orchestrator(db, provider, make_config()).run_tick(NOW)

    assert stats.failed == 1
    assert stats.ok == 1
    assert stats.polls_issued == 2
    rows = _snapshot_rows(db)
    outcomes = {row[1] for row in rows}
    assert outcomes == {"failed", "ok"}
    assert _observation_count(db) == 2


def test_sweep_abandoned_runs_at_tick_start(db: Engine) -> None:
    old = NOW - timedelta(hours=1)
    scope = SnapshotScope(
        vendor_fixture_ids=["fx-stale"],
        sportsbooks=["draftkings"],
        markets=["h2h"],
    )
    open_snapshot(db, VENDOR, "coarse", scope, clock=lambda: old)
    provider = StubProvider([])
    stats = Orchestrator(db, provider, make_config()).run_tick(NOW)

    assert stats.abandoned_swept == 1
    assert _snapshot_rows(db) == [(1, "abandoned", "coarse")]


def test_fresh_slate_cache_skips_list_fixtures(db: Engine) -> None:
    provider = StubProvider(
        [make_fixture()],
        quotes_by_id={"fx-a": [make_quote()]},
    )
    orch = Orchestrator(db, provider, make_config())
    first = orch.run_tick(NOW)
    second = orch.run_tick(NOW + timedelta(seconds=30))

    assert first.slate_refreshed is True
    assert second.slate_refreshed is False
    assert provider.list_calls == 1
    assert second.polls_issued == 0


def test_concurrent_tick_second_exits_without_snapshots(db: Engine) -> None:
    started = Event()
    release = Event()
    quotes = [make_quote()]

    class BlockingProvider(StubProvider):
        def get_odds(
            self,
            vendor_fixture_ids: list[str],
            sportsbooks: list[str],
            markets: list[str],
        ) -> list[Quote]:
            started.set()
            assert release.wait(timeout=10)
            return super().get_odds(vendor_fixture_ids, sportsbooks, markets)

    provider = BlockingProvider([make_fixture()], quotes_by_id={"fx-a": quotes})
    config = make_config()
    holder = Orchestrator(db, provider, config)
    waiter = Orchestrator(db, StubProvider([make_fixture()]), config)
    held: list[TickStats] = []

    def _run_holder() -> None:
        held.append(holder.run_tick(NOW))

    thread = Thread(target=_run_holder)
    thread.start()
    assert started.wait(timeout=10)
    skipped = waiter.run_tick(NOW)
    release.set()
    thread.join(timeout=10)

    assert skipped.lock_acquired is False
    assert skipped.polls_issued == 0
    assert held[0].lock_acquired is True
    assert held[0].ok == 1
    assert len(_snapshot_rows(db)) == 1


def test_proactive_coarsen_when_budget_low(db: Engine) -> None:
    provider = StubProvider(
        [make_fixture(vendor_fixture_id="fx-a", start_date=FINE_KICKOFF)],
        quotes_by_id={"fx-a": [make_quote()]},
        credits_remaining=50,
    )
    config = make_config(monthly_credit_budget=500, coarsen_budget_fraction=0.20)
    stats = Orchestrator(db, provider, config).run_tick(NOW)

    assert stats.ok == 1
    assert _snapshot_rows(db)[0][2] == "medium"


def test_dry_run_does_not_write_or_fetch_odds(db: Engine) -> None:
    provider = StubProvider(
        [make_fixture()],
        quotes_by_id={"fx-a": [make_quote()]},
    )
    stats = Orchestrator(db, provider, make_config()).run_tick(NOW, dry_run=True)

    assert stats.dry_run is True
    assert stats.polls_issued == 0
    assert provider.odds_calls == []
    assert provider.list_calls == 1
    assert _snapshot_rows(db) == []
    assert _observation_count(db) == 0
    with db.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM market.vendor_fixture")
        ).scalar_one()
    assert int(count) == 0


def test_due_fixtures_share_one_get_odds_call(db: Engine) -> None:
    fixtures = [
        make_fixture(vendor_fixture_id="fx-a"),
        make_fixture(vendor_fixture_id="fx-b"),
    ]
    provider = StubProvider(
        fixtures,
        quotes_by_id={
            "fx-a": [make_quote(vendor_fixture_id="fx-a", vendor_odds_id="odds-a")],
            "fx-b": [make_quote(vendor_fixture_id="fx-b", vendor_odds_id="odds-b")],
        },
    )
    stats = Orchestrator(db, provider, make_config()).run_tick(NOW)

    assert stats.ok == 2
    assert stats.polls_issued == 2
    assert provider.odds_calls == [["fx-a", "fx-b"]]
    assert _observation_count(db) == 2
    outcomes = {row[1] for row in _snapshot_rows(db)}
    assert outcomes == {"ok"}
