"""Capture cycle: cadence + OddsProvider + writer. The only composer."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from common.logging import get_logger
from ingest.odds.cadence import Tier, coarsen, determine_tier, poll_due
from ingest.odds.config import CaptureConfig
from ingest.odds.errors import RateBudgetExceeded
from ingest.odds.port import OddsProvider
from ingest.odds.types import Fixture, Quote, SnapshotId, SnapshotScope, WriteStats
from ingest.odds.writer import (
    close_snapshot,
    open_snapshot,
    sweep_abandoned,
    write_quotes,
)

_log = get_logger("ingest.odds.orchestrator")

_EMPTY_STATS = WriteStats(
    quotes_seen=0, quotes_written=0, max_vendor_ts=None, requests_made=0
)

_UPSERT_VENDOR_FIXTURE = text(
    """
    INSERT INTO market.vendor_fixture (
        vendor,
        vendor_fixture_id,
        league,
        season_year,
        season_type,
        vendor_season_week,
        start_date,
        status,
        home_team_vendor_id,
        away_team_vendor_id,
        home_abbr,
        away_abbr,
        venue_neutral,
        raw,
        last_seen_at
    )
    VALUES (
        :vendor,
        :vendor_fixture_id,
        :league,
        :season_year,
        :season_type,
        :vendor_season_week,
        :start_date,
        :status,
        :home_team_vendor_id,
        :away_team_vendor_id,
        :home_abbr,
        :away_abbr,
        :venue_neutral,
        CAST(:raw AS jsonb),
        :last_seen_at
    )
    ON CONFLICT (vendor, vendor_fixture_id) DO UPDATE SET
        start_date = EXCLUDED.start_date,
        status = EXCLUDED.status,
        last_seen_at = EXCLUDED.last_seen_at,
        vendor_season_week = EXCLUDED.vendor_season_week,
        home_abbr = EXCLUDED.home_abbr,
        away_abbr = EXCLUDED.away_abbr,
        venue_neutral = EXCLUDED.venue_neutral,
        raw = EXCLUDED.raw
    """
)

_LOAD_SNAPSHOTS = text(
    """
    SELECT started_at, outcome, scope
    FROM market.odds_snapshot
    WHERE vendor = :vendor
      AND outcome IS NOT NULL
      AND outcome NOT IN ('running', 'abandoned')
    ORDER BY started_at DESC
    """
)


class FixturePlan(BaseModel):
    """One fixture's cadence decision for this tick."""

    model_config = ConfigDict(frozen=True)

    vendor_fixture_id: str
    kickoff_at: datetime
    cadence_tier: Tier
    effective_tier: Tier
    due: bool


class TickStats(BaseModel):
    """Structured outcome of a single capture tick."""

    model_config = ConfigDict(frozen=True)

    lock_acquired: bool
    fixtures_considered: int
    polls_issued: int
    observations_written: int
    ok: int
    rate_limited: int
    failed: int
    abandoned_swept: int
    slate_refreshed: bool
    remaining_budget: int | None
    dry_run: bool = False
    fixtures: tuple[FixturePlan, ...] = ()


class _PollState:
    __slots__ = ("last_poll_at", "trailing_rate_limited")

    def __init__(
        self, last_poll_at: datetime | None, trailing_rate_limited: int
    ) -> None:
        self.last_poll_at = last_poll_at
        self.trailing_rate_limited = trailing_rate_limited


class Orchestrator:
    """Holds slate cache across ticks. ``now`` is injected every ``run_tick``."""

    def __init__(
        self, engine: Engine, provider: OddsProvider, config: CaptureConfig
    ) -> None:
        self._engine = engine
        self._provider = provider
        self._config = config
        self._fixtures: list[Fixture] = []
        self._slate_fetched_at: datetime | None = None

    def run_tick(self, now: datetime, *, dry_run: bool = False) -> TickStats:
        """One capture cycle. Acquires a process-wide advisory lock."""
        now = _require_aware(now)
        if dry_run:
            return self._run_locked(now, dry_run=True)

        with self._engine.connect() as lock_conn:
            if not _try_lock(lock_conn, self._config.advisory_lock_key):
                _log.info("tick_skipped_lock_held")
                return TickStats(
                    lock_acquired=False,
                    fixtures_considered=0,
                    polls_issued=0,
                    observations_written=0,
                    ok=0,
                    rate_limited=0,
                    failed=0,
                    abandoned_swept=0,
                    slate_refreshed=False,
                    remaining_budget=_credits_remaining(self._provider),
                )
            try:
                return self._run_locked(now, dry_run=False)
            finally:
                _unlock(lock_conn, self._config.advisory_lock_key)

    def _run_locked(self, now: datetime, *, dry_run: bool) -> TickStats:
        def clock() -> datetime:
            return now

        swept = 0
        if not dry_run:
            swept = sweep_abandoned(
                self._engine,
                older_than=now - self._config.abandon_after,
                clock=clock,
            )
        slate_refreshed = self._refresh_slate_if_stale(now, persist=not dry_run)
        poll_state = _hydrate_poll_state(self._engine, self._config.vendor)
        budget_steps = 1 if self._budget_pressure() else 0

        plans: list[FixturePlan] = []
        due: list[tuple[Fixture, FixturePlan]] = []
        for fixture in sorted(self._fixtures, key=lambda f: f.vendor_fixture_id):
            plan = self._plan_fixture(fixture, now, poll_state, budget_steps)
            if plan is None:
                continue
            plans.append(plan)
            if plan.due:
                due.append((fixture, plan))

        ok = 0
        failed = 0
        rate_limited = 0
        polls_issued = 0
        observations_written = 0

        if not dry_run:
            poll_stats = self._poll_due(due, now)
            ok = poll_stats["ok"]
            failed = poll_stats["failed"]
            rate_limited = poll_stats["rate_limited"]
            polls_issued = poll_stats["polls_issued"]
            observations_written = poll_stats["observations_written"]

        remaining = _credits_remaining(self._provider)
        stats = TickStats(
            lock_acquired=not dry_run,
            fixtures_considered=len(plans),
            polls_issued=polls_issued,
            observations_written=observations_written,
            ok=ok,
            rate_limited=rate_limited,
            failed=failed,
            abandoned_swept=swept,
            slate_refreshed=slate_refreshed,
            remaining_budget=remaining,
            dry_run=dry_run,
            fixtures=tuple(plans),
        )
        _log.info(
            "tick",
            dry_run=dry_run,
            fixtures_considered=stats.fixtures_considered,
            polls_issued=stats.polls_issued,
            observations_written=stats.observations_written,
            rate_limited=stats.rate_limited,
            failed=stats.failed,
            ok=stats.ok,
            remaining_budget=remaining,
        )
        return stats

    def _plan_fixture(
        self,
        fixture: Fixture,
        now: datetime,
        poll_state: dict[str, _PollState],
        budget_steps: int,
    ) -> FixturePlan | None:
        window_end = now + self._config.capture_window
        if fixture.start_date < now or fixture.start_date > window_end:
            return None
        cadence_tier = determine_tier(fixture.start_date, now)
        if cadence_tier is Tier.none:
            return None
        state = poll_state.get(fixture.vendor_fixture_id, _PollState(None, 0))
        effective = _apply_coarsen(
            cadence_tier, state.trailing_rate_limited + budget_steps
        )
        due = poll_due(
            state.last_poll_at,
            effective,
            now,
            self._config.intervals,
        )
        return FixturePlan(
            vendor_fixture_id=fixture.vendor_fixture_id,
            kickoff_at=fixture.start_date,
            cadence_tier=cadence_tier,
            effective_tier=effective,
            due=due,
        )

    def _poll_due(
        self, due: list[tuple[Fixture, FixturePlan]], now: datetime
    ) -> dict[str, int]:
        """Open per-fixture snapshots; fetch odds once for the remaining due set."""
        ok = 0
        failed = 0
        rate_limited = 0
        polls_issued = 0
        observations_written = 0
        pending = list(due)
        quotes_by_fixture: dict[str, list[Quote]] | None = None
        sportsbooks = list(self._config.sportsbooks)
        markets = list(self._config.markets)

        while pending:
            fixture, plan = pending[0]
            polls_issued += 1
            snapshot_id = self._open_fixture_snapshot(fixture, plan, now)
            requests_made = 0
            try:
                if quotes_by_fixture is None:
                    remaining_ids = [item[0].vendor_fixture_id for item in pending]
                    quotes = self._provider.get_odds(
                        remaining_ids, sportsbooks, markets
                    )
                    quotes_by_fixture = _index_quotes(quotes)
                    requests_made = 1
                written = self._write_and_close_ok(
                    snapshot_id,
                    quotes_by_fixture.get(fixture.vendor_fixture_id, []),
                    now,
                    requests_made,
                )
                observations_written += written
                ok += 1
                pending.pop(0)
            except RateBudgetExceeded as exc:
                self._close_unsuccessful(snapshot_id, "rate_limited", exc, now)
                rate_limited += 1
                pending.pop(0)
                break
            except Exception as exc:
                self._close_unsuccessful(snapshot_id, "failed", exc, now)
                _log.exception(
                    "fixture_poll_failed",
                    vendor_fixture_id=fixture.vendor_fixture_id,
                )
                failed += 1
                quotes_by_fixture = None
                pending.pop(0)

        return {
            "ok": ok,
            "failed": failed,
            "rate_limited": rate_limited,
            "polls_issued": polls_issued,
            "observations_written": observations_written,
        }

    def _open_fixture_snapshot(
        self, fixture: Fixture, plan: FixturePlan, now: datetime
    ) -> SnapshotId:
        def clock() -> datetime:
            return now

        scope = SnapshotScope(
            vendor_fixture_ids=[fixture.vendor_fixture_id],
            sportsbooks=list(self._config.sportsbooks),
            markets=list(self._config.markets),
        )
        return open_snapshot(
            self._engine,
            self._config.vendor,
            plan.effective_tier.value,
            scope,
            clock=clock,
        )

    def _write_and_close_ok(
        self,
        snapshot_id: SnapshotId,
        quotes: list[Quote],
        now: datetime,
        requests_made: int,
    ) -> int:
        def clock() -> datetime:
            return now

        stats = write_quotes(self._engine, snapshot_id, quotes, clock=clock)
        stats.requests_made = requests_made
        close_snapshot(self._engine, snapshot_id, "ok", stats, clock=clock)
        return stats.quotes_written

    def _close_unsuccessful(
        self,
        snapshot_id: SnapshotId,
        outcome: str,
        exc: BaseException,
        now: datetime,
    ) -> None:
        def clock() -> datetime:
            return now

        close_snapshot(
            self._engine,
            snapshot_id,
            outcome,
            _EMPTY_STATS,
            error=_error_payload(exc),
            clock=clock,
        )

    def _refresh_slate_if_stale(self, now: datetime, *, persist: bool) -> bool:
        ttl = self._config.slate_ttl
        fetched = self._slate_fetched_at
        if fetched is not None and now - fetched < ttl:
            return False
        fixtures = self._provider.list_fixtures(
            self._config.league,
            self._config.season_year,
            start_after=now,
            start_before=now + self._config.capture_window,
        )
        if persist:
            _upsert_fixtures(self._engine, fixtures, now)
        self._fixtures = fixtures
        self._slate_fetched_at = now
        return True

    def _budget_pressure(self) -> bool:
        remaining = _credits_remaining(self._provider)
        if remaining is None:
            return False
        threshold = self._config.coarsen_budget_fraction * float(
            self._config.monthly_credit_budget
        )
        return float(remaining) < threshold


def _apply_coarsen(tier: Tier, steps: int) -> Tier:
    for _ in range(max(0, steps)):
        tier = coarsen(tier)
        if tier is Tier.none:
            return tier
    return tier


def _index_quotes(quotes: list[Quote]) -> dict[str, list[Quote]]:
    by_fixture: dict[str, list[Quote]] = defaultdict(list)
    for quote in quotes:
        by_fixture[quote.vendor_fixture_id].append(quote)
    return by_fixture


def _hydrate_poll_state(engine: Engine, vendor: str) -> dict[str, _PollState]:
    events: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    with engine.connect() as conn:
        rows = conn.execute(_LOAD_SNAPSHOTS, {"vendor": vendor})
        for row in rows:
            scope = row.scope
            if not isinstance(scope, dict):
                continue
            ids = scope.get("vendor_fixture_ids")
            if not isinstance(ids, list):
                continue
            started_at = row.started_at
            outcome = row.outcome
            if not isinstance(outcome, str):
                continue
            for fixture_id in ids:
                if isinstance(fixture_id, str):
                    events[fixture_id].append((started_at, outcome))
    states: dict[str, _PollState] = {}
    for fixture_id, items in events.items():
        items.sort(key=lambda item: item[0], reverse=True)
        trailing = 0
        for _started, outcome in items:
            if outcome == "rate_limited":
                trailing += 1
            else:
                break
        states[fixture_id] = _PollState(items[0][0], trailing)
    return states


def _upsert_fixtures(engine: Engine, fixtures: list[Fixture], now: datetime) -> None:
    if not fixtures:
        return
    with engine.begin() as conn:
        for fixture in fixtures:
            conn.execute(
                _UPSERT_VENDOR_FIXTURE,
                {
                    "vendor": fixture.vendor,
                    "vendor_fixture_id": fixture.vendor_fixture_id,
                    "league": fixture.league,
                    "season_year": fixture.season_year,
                    "season_type": fixture.season_type,
                    "vendor_season_week": fixture.vendor_season_week,
                    "start_date": fixture.start_date,
                    "status": fixture.status,
                    "home_team_vendor_id": fixture.home_team_vendor_id,
                    "away_team_vendor_id": fixture.away_team_vendor_id,
                    "home_abbr": fixture.home_abbr,
                    "away_abbr": fixture.away_abbr,
                    "venue_neutral": fixture.venue_neutral,
                    "raw": json.dumps(fixture.raw),
                    "last_seen_at": now,
                },
            )


def _try_lock(conn: Connection, key: int) -> bool:
    acquired = conn.execute(
        text("SELECT pg_try_advisory_lock(:k1, :k2)"),
        {"k1": key, "k2": 0},
    ).scalar()
    conn.commit()
    return bool(acquired)


def _unlock(conn: Connection, key: int) -> None:
    conn.execute(
        text("SELECT pg_advisory_unlock(:k1, :k2)"),
        {"k1": key, "k2": 0},
    )
    conn.commit()


def _credits_remaining(provider: object) -> int | None:
    remaining = getattr(provider, "credits_remaining", None)
    if isinstance(remaining, int):
        return remaining
    return None


def _error_payload(exc: BaseException) -> dict[str, Any]:
    return {"type": type(exc).__name__, "message": str(exc)}


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must be timezone-aware")
    return value
