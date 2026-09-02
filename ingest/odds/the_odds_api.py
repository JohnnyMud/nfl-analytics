"""The Odds API v4 adapter.

Featured game markets (h2h, spreads, totals) are fetched as a full slate in one
``GET /v4/sports/{sport}/odds`` call. ``get_odds`` still accepts a list of
fixture IDs for port symmetry; filtering is client-side. Granularity is
per-sport, not per-game.

Player props use the per-event odds endpoint and are gated by
``include_player_props``. When the flag is off, prop markets are skipped rather
than failing hard — they may require Pro.

Free-tier volume (500 credits/month) fits a coarse weekly cadence. The
research-grade 2-minute closing snapshots require Pro. This adapter does not
change cadence; it raises ``RateBudgetExceeded`` so the orchestrator can
coarsen. Historical endpoints (10× credit cost, paid-only) are not used.

``vendor_odds_id`` is synthesized as
``{event_id}:{bookmaker_key}:{market_key}:{outcome_name}:{point}:{description}``
because The Odds API has no stable odds identifier.
"""

from __future__ import annotations

import math
import os
import random
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, NoReturn

import httpx

from common.logging import get_logger
from ingest.odds.errors import (
    RateBudgetExceeded,
    VendorContractError,
    VendorTransportError,
)
from ingest.odds.types import Fixture, FixtureResult, MarketRef, Quote

VENDOR: Final = "the-odds-api"
BASE_URL: Final = "https://api.the-odds-api.com"
DEFAULT_MONTHLY_CREDIT_BUDGET: Final = 500
FEATURED_MARKETS: Final[frozenset[str]] = frozenset(
    {"h2h", "spreads", "totals", "outrights"}
)
NFL_REGULAR_SPORT: Final = "americanfootball_nfl"
NFL_PRESEASON_SPORT: Final = "americanfootball_nfl_preseason"
NFL_SPORT_KEYS: Final[tuple[str, ...]] = (NFL_PRESEASON_SPORT, NFL_REGULAR_SPORT)
OUT_OF_USAGE_CREDITS: Final = "OUT_OF_USAGE_CREDITS"
HISTORICAL_CREDIT_MULTIPLIER: Final = 10
_BOOKMAKER_REGION_GROUP: Final = 10
_MARKET_NAMES: Final[dict[str, str]] = {
    "h2h": "moneyline",
    "spreads": "spread",
    "totals": "total",
    "outrights": "outrights",
}

_log = get_logger("ingest.odds.the_odds_api")


def credit_cost(
    *,
    markets: Sequence[str],
    regions: Sequence[str],
    bookmakers: Sequence[str] | None = None,
    historical: bool = False,
) -> int:
    """Credits for one odds request: ``markets × region_units`` (×10 if historical).

    When ``bookmakers`` is set it replaces ``regions`` for billing: every group
    of 10 bookmakers is one region-unit.
    """
    region_units = _region_units(regions, bookmakers)
    cost = len(markets) * region_units
    if historical:
        cost *= HISTORICAL_CREDIT_MULTIPLIER
    return cost


def _region_units(regions: Sequence[str], bookmakers: Sequence[str] | None) -> int:
    if bookmakers:
        return max(1, math.ceil(len(bookmakers) / _BOOKMAKER_REGION_GROUP))
    return len(regions)


def american_to_decimal(american: int) -> Decimal:
    """Convert American odds to decimal. American 0 is not a valid price."""
    if american > 0:
        value = Decimal(1) + Decimal(american) / Decimal(100)
    elif american < 0:
        value = Decimal(1) + Decimal(100) / Decimal(abs(american))
    else:
        raise VendorContractError("american odds of 0 are invalid")
    return value.quantize(Decimal("0.0001"))


def _synthesize_vendor_odds_id(
    event_id: str,
    bookmaker_key: str,
    market_key: str,
    outcome_name: str,
    point: Any,
    description: str | None,
) -> str:
    point_s = "" if point is None else str(point)
    desc_s = description or ""
    return f"{event_id}:{bookmaker_key}:{market_key}:{outcome_name}:{point_s}:{desc_s}"


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_dict(value: Any, *, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VendorContractError(f"expected {what} to be an object, got {type(value)}")
    return value


def _as_list(value: Any, *, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise VendorContractError(f"expected {what} to be an array, got {type(value)}")
    return value


def _header_int(headers: httpx.Headers, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _league_sport_keys(league: str) -> tuple[str, ...]:
    if league.lower() != "nfl":
        raise VendorContractError(f"unsupported league {league!r}")
    return NFL_SPORT_KEYS


def _season_type_for_sport(sport_key: str) -> str:
    if sport_key == NFL_PRESEASON_SPORT:
        return "Preseason"
    return "Regular Season"


def _partition_markets(
    markets: Sequence[str],
) -> tuple[list[str], list[str], list[str]]:
    featured: list[str] = []
    props: list[str] = []
    extra: list[str] = []
    for market in markets:
        if market in FEATURED_MARKETS:
            featured.append(market)
        elif market.startswith("player_"):
            props.append(market)
        else:
            extra.append(market)
    return featured, props, extra


def _optional_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return _parse_utc(value)


def _selection_line(name: str) -> str | None:
    lowered = name.lower()
    if lowered in {"over", "under"}:
        return lowered
    return None


class _TokenBucket:
    """Client-side limiter sized below The Odds API's 30 req/s ceiling."""

    def __init__(
        self,
        *,
        rate: float,
        capacity: float,
        clock: Callable[[], datetime],
        sleeper: Callable[[float], None],
    ) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._clock = clock
        self._sleeper = sleeper
        self._updated_at = clock()

    def consume(self, tokens: float = 1.0) -> None:
        now = self._clock()
        elapsed = max(0.0, (now - self._updated_at).total_seconds())
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._updated_at = now
        if self._tokens >= tokens:
            self._tokens -= tokens
            return
        wait = (tokens - self._tokens) / self._rate
        self._sleeper(wait)
        self._tokens = 0.0
        self._updated_at = self._clock()


class _CreditBudget:
    """In-memory monthly credit tracker.

    Process restart loses local state until ``x-requests-*`` headers (or a free
    ``GET /v4/sports`` call) arrive. The first paid call of a new process is
    still preflighted against the configured budget.
    """

    def __init__(
        self,
        monthly_budget: int,
        *,
        clock: Callable[[], datetime],
        used: int = 0,
    ) -> None:
        self.monthly_budget = monthly_budget
        self._clock = clock
        self._month = self._month_key()
        self._used = used
        self._remaining: int | None = None

    def _month_key(self) -> str:
        now = self._clock()
        return f"{now.year:04d}-{now.month:02d}"

    def _ensure_month(self) -> None:
        month = self._month_key()
        if self._month != month:
            self._month = month
            self._used = 0
            self._remaining = None

    @property
    def used(self) -> int:
        self._ensure_month()
        return self._used

    @property
    def remaining(self) -> int | None:
        self._ensure_month()
        return self._remaining

    @property
    def has_vendor_reading(self) -> bool:
        self._ensure_month()
        return self._remaining is not None

    def preflight(self, cost: int) -> None:
        self._ensure_month()
        if cost <= 0:
            return
        if self._used + cost > self.monthly_budget:
            raise RateBudgetExceeded(
                f"planned cost {cost} would exceed monthly budget "
                f"{self.monthly_budget} (used={self._used})"
            )
        if self._remaining is not None and cost > self._remaining:
            raise RateBudgetExceeded(
                f"planned cost {cost} exceeds vendor remaining {self._remaining}"
            )

    def record_headers(self, headers: httpx.Headers) -> None:
        self._ensure_month()
        used = _header_int(headers, "x-requests-used")
        remaining = _header_int(headers, "x-requests-remaining")
        last = _header_int(headers, "x-requests-last")
        if used is not None:
            self._used = used
        elif last is not None:
            self._used += last
        if remaining is not None:
            self._remaining = remaining
        elif last is not None and self._remaining is not None:
            self._remaining = max(0, self._remaining - last)

    def mark_exhausted(self) -> None:
        self._ensure_month()
        self._remaining = 0
        self._used = self.monthly_budget


class TheOddsApiAdapter:
    """``OddsProvider`` for The Odds API v4. See module docstring."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        monthly_credit_budget: int = DEFAULT_MONTHLY_CREDIT_BUDGET,
        regions: Sequence[str] = ("us",),
        bookmakers: Sequence[str] | None = None,
        include_player_props: bool = False,
        max_retries: int = 3,
        timeout: float = 30.0,
        tokens_per_second: float = 10.0,
        credits_used: int = 0,
        sync_quota_on_start: bool = True,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("ODDS_API_KEY", "")
        if not key:
            raise VendorContractError("ODDS_API_KEY is missing")
        self._api_key = key
        self._regions = tuple(regions)
        self._bookmakers = tuple(bookmakers) if bookmakers else None
        self._include_player_props = include_player_props
        self._max_retries = max_retries
        self._sync_quota_on_start = sync_quota_on_start
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._sleeper = sleeper or time.sleep
        self._rng: random.Random = rng if rng is not None else random.Random()
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._budget = _CreditBudget(
            monthly_credit_budget, clock=self._clock, used=credits_used
        )
        self._bucket = _TokenBucket(
            rate=tokens_per_second,
            capacity=tokens_per_second,
            clock=self._clock,
            sleeper=self._sleeper,
        )
        self._fixture_sport: dict[str, str] = {}

    @property
    def credits_used(self) -> int:
        return self._budget.used

    @property
    def credits_remaining(self) -> int | None:
        return self._budget.remaining

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> TheOddsApiAdapter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def list_fixtures(
        self,
        league: str,
        season_year: int,
        *,
        start_after: datetime,
        start_before: datetime,
    ) -> list[Fixture]:
        fixtures: list[Fixture] = []
        params = {
            "apiKey": self._api_key,
            "commenceTimeFrom": _iso_z(start_after),
            "commenceTimeTo": _iso_z(start_before),
            "dateFormat": "iso",
        }
        for sport_key in _league_sport_keys(league):
            payload = self._send(
                "GET",
                f"/v4/sports/{sport_key}/events",
                params=params,
                credit_cost=0,
            )
            for item in _as_list(payload, what="events"):
                event = _as_dict(item, what="event")
                fixture = self._normalize_fixture(event, league, season_year)
                self._remember_sport(fixture.vendor_fixture_id, sport_key)
                fixtures.append(fixture)
        return fixtures

    def list_markets(
        self,
        vendor_fixture_id: str,
        sportsbooks: list[str],
    ) -> list[MarketRef]:
        sport_key = self._sport_for(vendor_fixture_id)
        params = {
            "apiKey": self._api_key,
            "dateFormat": "iso",
            **self._book_params(sportsbooks),
        }
        payload = self._send(
            "GET",
            f"/v4/sports/{sport_key}/events/{vendor_fixture_id}/markets",
            params=params,
            credit_cost=1,
        )
        event = _as_dict(payload, what="event markets")
        self._remember_sport(vendor_fixture_id, str(event.get("sport_key", sport_key)))
        return self._normalize_markets(event, sportsbooks)

    def get_odds(
        self,
        vendor_fixture_ids: list[str],
        sportsbooks: list[str],
        markets: list[str],
    ) -> list[Quote]:
        """Current quotes. Featured markets are one full-slate call per sport."""
        if not vendor_fixture_ids:
            return []

        featured, props, extra = _partition_markets(markets)
        if not self._include_player_props:
            props = []

        quotes: list[Quote] = []
        wanted = set(vendor_fixture_ids)

        if featured:
            for sport_key in self._sports_for_ids(vendor_fixture_ids):
                quotes.extend(
                    self._fetch_featured_odds(sport_key, wanted, sportsbooks, featured)
                )

        event_markets = extra + props
        if event_markets:
            for fixture_id in vendor_fixture_ids:
                quotes.extend(
                    self._fetch_event_odds(fixture_id, sportsbooks, event_markets)
                )
        return quotes

    def get_results(self, vendor_fixture_ids: list[str]) -> list[FixtureResult]:
        if not vendor_fixture_ids:
            return []
        results: list[FixtureResult] = []
        wanted = set(vendor_fixture_ids)
        for sport_key in self._sports_for_ids(vendor_fixture_ids):
            ids_for_sport = [
                fid for fid in vendor_fixture_ids if self._sport_for(fid) == sport_key
            ]
            params = {
                "apiKey": self._api_key,
                "dateFormat": "iso",
                "daysFrom": "1",
                "eventIds": ",".join(ids_for_sport),
            }
            payload = self._send(
                "GET",
                f"/v4/sports/{sport_key}/scores",
                params=params,
                credit_cost=2,
            )
            for item in _as_list(payload, what="scores"):
                event = _as_dict(item, what="score event")
                result = self._normalize_result(event)
                if result.vendor_fixture_id in wanted:
                    self._remember_sport(
                        result.vendor_fixture_id,
                        str(event.get("sport_key", sport_key)),
                    )
                    results.append(result)
        return results

    def _fetch_featured_odds(
        self,
        sport_key: str,
        wanted: set[str],
        sportsbooks: Sequence[str],
        markets: Sequence[str],
    ) -> list[Quote]:
        params = {
            "apiKey": self._api_key,
            "markets": ",".join(markets),
            "oddsFormat": "american",
            "dateFormat": "iso",
            **self._book_params(sportsbooks),
        }
        cost = credit_cost(
            markets=markets,
            regions=self._regions,
            bookmakers=self._effective_bookmakers(sportsbooks),
        )
        payload = self._send(
            "GET",
            f"/v4/sports/{sport_key}/odds",
            params=params,
            credit_cost=cost,
        )
        quotes: list[Quote] = []
        for item in _as_list(payload, what="odds"):
            event = _as_dict(item, what="odds event")
            event_id = str(event.get("id", ""))
            if event_id:
                self._remember_sport(event_id, str(event.get("sport_key", sport_key)))
            if event_id not in wanted:
                continue
            quotes.extend(self._quotes_from_event(event, sportsbooks))
        return quotes

    def _fetch_event_odds(
        self,
        vendor_fixture_id: str,
        sportsbooks: Sequence[str],
        markets: Sequence[str],
    ) -> list[Quote]:
        sport_key = self._sport_for(vendor_fixture_id)
        params = {
            "apiKey": self._api_key,
            "markets": ",".join(markets),
            "oddsFormat": "american",
            "dateFormat": "iso",
            **self._book_params(sportsbooks),
        }
        cost = credit_cost(
            markets=markets,
            regions=self._regions,
            bookmakers=self._effective_bookmakers(sportsbooks),
        )
        payload = self._send(
            "GET",
            f"/v4/sports/{sport_key}/events/{vendor_fixture_id}/odds",
            params=params,
            credit_cost=cost,
        )
        event = _as_dict(payload, what="event odds")
        self._remember_sport(vendor_fixture_id, str(event.get("sport_key", sport_key)))
        return self._quotes_from_event(event, sportsbooks)

    def _book_params(self, sportsbooks: Sequence[str]) -> dict[str, str]:
        books = self._effective_bookmakers(sportsbooks)
        if books:
            return {"bookmakers": ",".join(books)}
        return {"regions": ",".join(self._regions)}

    def _effective_bookmakers(
        self, sportsbooks: Sequence[str]
    ) -> tuple[str, ...] | None:
        if sportsbooks:
            return tuple(sportsbooks)
        return self._bookmakers

    def _sport_for(self, vendor_fixture_id: str) -> str:
        return self._fixture_sport.get(vendor_fixture_id, NFL_REGULAR_SPORT)

    def _sports_for_ids(self, vendor_fixture_ids: Sequence[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for fixture_id in vendor_fixture_ids:
            sport = self._sport_for(fixture_id)
            if sport not in seen:
                seen.add(sport)
                ordered.append(sport)
        return ordered

    def _remember_sport(self, vendor_fixture_id: str, sport_key: str) -> None:
        if vendor_fixture_id:
            self._fixture_sport[vendor_fixture_id] = sport_key

    def _ensure_quota(self) -> None:
        if not self._sync_quota_on_start or self._budget.has_vendor_reading:
            return
        self._send(
            "GET",
            "/v4/sports",
            params={"apiKey": self._api_key},
            credit_cost=0,
            seeding=True,
        )

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str],
        credit_cost: int,
        seeding: bool = False,
    ) -> Any:
        if credit_cost > 0 and not seeding:
            self._ensure_quota()
        if credit_cost > 0:
            self._budget.preflight(credit_cost)

        attempts = self._max_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            self._bucket.consume()
            try:
                response = self._client.request(method, path, params=dict(params))
            except httpx.RequestError as exc:
                last_error = VendorTransportError(str(exc))
                if attempt + 1 >= attempts:
                    raise last_error from exc
                delay = self._backoff(attempt)
                _log.warning(
                    "odds_vendor_transport_retry",
                    attempt=attempt + 1,
                    delay_s=delay,
                    error=str(exc),
                    path=path,
                )
                self._sleeper(delay)
                continue

            self._budget.record_headers(response.headers)

            if response.status_code == 429 or response.status_code >= 500:
                last_error = VendorTransportError(
                    f"vendor HTTP {response.status_code} for {path}"
                )
                if attempt + 1 >= attempts:
                    raise last_error
                delay = self._backoff(attempt)
                _log.warning(
                    "odds_vendor_retry",
                    attempt=attempt + 1,
                    delay_s=delay,
                    status=response.status_code,
                    path=path,
                )
                self._sleeper(delay)
                continue

            if response.status_code >= 400:
                self._raise_client_error(response)

            try:
                return response.json()
            except ValueError as exc:
                raise VendorContractError(
                    f"vendor response for {path} is not JSON"
                ) from exc

        raise last_error or VendorTransportError(f"request to {path} failed")

    def _raise_client_error(self, response: httpx.Response) -> NoReturn:
        error_code: str | None = None
        body: Any
        try:
            body = response.json()
        except ValueError:
            body = response.text
        if isinstance(body, dict):
            code = body.get("error_code")
            if isinstance(code, str):
                error_code = code
        if error_code == OUT_OF_USAGE_CREDITS:
            self._budget.mark_exhausted()
            raise RateBudgetExceeded(
                f"vendor reports usage credits exhausted: {body!r}"
            )
        raise VendorContractError(f"vendor HTTP {response.status_code}: {body!r}")

    def _backoff(self, attempt: int) -> float:
        base = 0.5 * (2**attempt)
        jitter = 0.5 + self._rng.random()
        return float(base * jitter)

    def _normalize_fixture(
        self, event: dict[str, Any], league: str, season_year: int
    ) -> Fixture:
        sport_key = str(event.get("sport_key", NFL_REGULAR_SPORT))
        commence = event.get("commence_time")
        if not isinstance(commence, str):
            raise VendorContractError("event missing commence_time")
        event_id = event.get("id")
        home = event.get("home_team")
        away = event.get("away_team")
        if not isinstance(event_id, str) or not event_id:
            raise VendorContractError("event missing id")
        if not isinstance(home, str) or not isinstance(away, str):
            raise VendorContractError("event missing home_team or away_team")
        return Fixture(
            vendor=VENDOR,
            vendor_fixture_id=event_id,
            league=league.lower(),
            season_year=season_year,
            season_type=_season_type_for_sport(sport_key),
            vendor_season_week=None,
            start_date=_parse_utc(commence),
            status="scheduled",
            home_team_vendor_id=home,
            away_team_vendor_id=away,
            home_abbr=None,
            away_abbr=None,
            venue_neutral=None,
            raw=event,
        )

    def _normalize_markets(
        self, event: dict[str, Any], sportsbooks: Sequence[str]
    ) -> list[MarketRef]:
        event_id = str(event.get("id", ""))
        if not event_id:
            raise VendorContractError("event markets missing id")
        wanted_books = set(sportsbooks) if sportsbooks else None
        refs: list[MarketRef] = []
        for book in event.get("bookmakers") or []:
            book_obj = _as_dict(book, what="bookmaker")
            book_key = str(book_obj.get("key", ""))
            if wanted_books is not None and book_key not in wanted_books:
                continue
            markets = book_obj.get("markets") or []
            if not markets:
                continue
            for market in _as_list(markets, what="markets"):
                market_obj = _as_dict(market, what="market")
                market_key = str(market_obj.get("key", ""))
                if not market_key:
                    raise VendorContractError("market missing key")
                refs.append(
                    MarketRef(
                        vendor=VENDOR,
                        vendor_fixture_id=event_id,
                        sportsbook=book_key,
                        market_id=market_key,
                        market_name=_MARKET_NAMES.get(market_key, market_key),
                        raw=market_obj,
                    )
                )
        return refs

    def _quotes_from_event(
        self, event: dict[str, Any], sportsbooks: Sequence[str]
    ) -> list[Quote]:
        event_id = str(event.get("id", ""))
        if not event_id:
            raise VendorContractError("odds event missing id")
        wanted_books = set(sportsbooks) if sportsbooks else None
        quotes: list[Quote] = []
        for book in event.get("bookmakers") or []:
            book_obj = _as_dict(book, what="bookmaker")
            book_key = str(book_obj.get("key", ""))
            if wanted_books is not None and book_key not in wanted_books:
                continue
            book_ts = _optional_utc(book_obj.get("last_update"))
            for market in book_obj.get("markets") or []:
                market_obj = _as_dict(market, what="market")
                quotes.extend(
                    self._quotes_from_market(event_id, book_key, market_obj, book_ts)
                )
        return quotes

    def _quotes_from_market(
        self,
        event_id: str,
        book_key: str,
        market: dict[str, Any],
        book_timestamp: datetime | None,
    ) -> list[Quote]:
        market_key = str(market.get("key", ""))
        if not market_key:
            raise VendorContractError("market missing key")
        vendor_ts = _optional_utc(market.get("last_update")) or book_timestamp
        is_main = market_key in FEATURED_MARKETS
        quotes: list[Quote] = []
        for outcome in _as_list(market.get("outcomes") or [], what="outcomes"):
            outcome_obj = _as_dict(outcome, what="outcome")
            quotes.append(
                _normalize_quote(
                    event_id,
                    book_key,
                    market_key,
                    outcome_obj,
                    vendor_ts,
                    is_main,
                )
            )
        return quotes

    def _normalize_result(self, event: dict[str, Any]) -> FixtureResult:
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise VendorContractError("score event missing id")
        completed = bool(event.get("completed", False))
        home = event.get("home_team")
        away = event.get("away_team")
        home_score: int | None = None
        away_score: int | None = None
        scores = event.get("scores")
        if isinstance(scores, list) and isinstance(home, str) and isinstance(away, str):
            by_name: dict[str, int] = {}
            for row in scores:
                row_obj = _as_dict(row, what="score")
                name = row_obj.get("name")
                raw_score = row_obj.get("score")
                if isinstance(name, str) and raw_score is not None:
                    by_name[name] = int(raw_score)
            home_score = by_name.get(home)
            away_score = by_name.get(away)
        return FixtureResult(
            vendor=VENDOR,
            vendor_fixture_id=event_id,
            completed=completed,
            home_score=home_score,
            away_score=away_score,
            vendor_timestamp=_optional_utc(event.get("last_update")),
            raw=event,
        )


def _normalize_quote(
    event_id: str,
    book_key: str,
    market_key: str,
    outcome: dict[str, Any],
    vendor_timestamp: datetime | None,
    is_main: bool,
) -> Quote:
    name = outcome.get("name")
    price = outcome.get("price")
    if not isinstance(name, str) or not name:
        raise VendorContractError("outcome missing name")
    if not isinstance(price, int | float):
        raise VendorContractError(f"outcome {name!r} missing numeric price")
    price_american = int(price)
    description = outcome.get("description")
    player_id = description if isinstance(description, str) and description else None
    point = outcome.get("point")
    points: Decimal | None
    if point is None:
        points = None
    else:
        points = Decimal(str(point))
    return Quote(
        vendor=VENDOR,
        vendor_odds_id=_synthesize_vendor_odds_id(
            event_id, book_key, market_key, name, point, player_id
        ),
        vendor_fixture_id=event_id,
        sportsbook=book_key,
        market_id=market_key,
        selection=name,
        selection_line=_selection_line(name),
        points=points,
        price_american=price_american,
        price_decimal=american_to_decimal(price_american),
        is_main=is_main,
        vendor_player_id=player_id,
        vendor_timestamp=vendor_timestamp,
        availability="open",
        raw=outcome,
    )
