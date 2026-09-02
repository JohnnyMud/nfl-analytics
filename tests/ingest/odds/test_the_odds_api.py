"""Offline contract tests for The Odds API adapter. No live network."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from ingest.odds.errors import (
    RateBudgetExceeded,
    VendorContractError,
    VendorTransportError,
)
from ingest.odds.the_odds_api import (
    VENDOR,
    TheOddsApiAdapter,
    american_to_decimal,
    credit_cost,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "vendor" / "the_odds_api"

SEA_NE_ID = "42db668449664943833b5c04a583328a"
DAL_CIN_ID = "2fd335893dbb8ab9c0e1aea6c98a969c"
ATL_ARI_ID = "a512a48a58c4329048174217b2cc7ce0"
EMPTY_MARKETS_ID = "empty-markets-fixture-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
PRESEASON_ID = "preseason-event-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

FEATURED = ["h2h", "spreads", "totals"]
QUOTA_HEADERS = {
    "x-requests-used": "3",
    "x-requests-remaining": "497",
    "x-requests-last": "3",
}


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def json_response(
    payload: Any,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=payload,
        headers=headers or QUOTA_HEADERS,
    )


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.Client, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = httpx.Client(
        base_url="https://api.the-odds-api.com",
        transport=httpx.MockTransport(wrapped),
    )
    return client, calls


def make_adapter(
    client: httpx.Client,
    *,
    slept: list[float] | None = None,
    **kwargs: Any,
) -> TheOddsApiAdapter:
    defaults: dict[str, Any] = {
        "api_key": "test-key",
        "client": client,
        "sync_quota_on_start": False,
        "clock": lambda: datetime(2026, 9, 1, tzinfo=UTC),
        "sleeper": (slept.append if slept is not None else (lambda _s: None)),
        "max_retries": 3,
    }
    defaults.update(kwargs)
    return TheOddsApiAdapter(**defaults)


def _path(request: httpx.Request) -> str:
    return request.url.path


def test_credit_cost_multi_market_multi_region() -> None:
    assert credit_cost(markets=["h2h", "spreads", "totals"], regions=["us", "uk"]) == 6


def test_credit_cost_bookmakers_groups_of_ten() -> None:
    books = [f"book{i}" for i in range(11)]
    assert credit_cost(markets=["h2h"], regions=["us"], bookmakers=books) == 2
    assert (
        credit_cost(markets=["h2h", "spreads"], regions=["us"], bookmakers=books[:10])
        == 2
    )


def test_historical_credit_multiplier_is_ten() -> None:
    assert credit_cost(markets=["h2h"], regions=["us"], historical=True) == 10


def test_rate_budget_exceeded_before_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"HTTP must not be called, got {request.url}")

    client, calls = make_client(handler)
    adapter = make_adapter(client, credits_used=498, monthly_credit_budget=500)
    with pytest.raises(RateBudgetExceeded):
        adapter.get_odds([SEA_NE_ID], [], FEATURED)
    assert calls == []


def test_headers_update_running_spend_then_preflight_blocks() -> None:
    game_odds = load_json("nfl_odds_game_markets.json")
    hits = {"odds": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if _path(request).endswith("/odds"):
            hits["odds"] += 1
            return json_response(
                game_odds,
                headers={
                    "x-requests-used": "498",
                    "x-requests-remaining": "2",
                    "x-requests-last": "3",
                },
            )
        raise AssertionError(f"unexpected {request.url}")

    client, _calls = make_client(handler)
    adapter = make_adapter(client)
    quotes = adapter.get_odds([SEA_NE_ID], [], FEATURED)
    assert quotes
    assert adapter.credits_used == 498
    assert adapter.credits_remaining == 2
    with pytest.raises(RateBudgetExceeded):
        adapter.get_odds([DAL_CIN_ID], [], FEATURED)
    assert hits["odds"] == 1


def test_normalization_preserves_raw_and_utc() -> None:
    events = load_json("nfl_events.json")
    preseason = load_json("nfl_events_preseason.json")
    game_odds = load_json("nfl_odds_game_markets.json")

    def handler(request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if path.endswith("/americanfootball_nfl/events"):
            return json_response(events)
        if path.endswith("/americanfootball_nfl_preseason/events"):
            return json_response(preseason)
        if path.endswith("/americanfootball_nfl/odds"):
            return json_response(game_odds)
        raise AssertionError(f"unexpected {request.url}")

    client, _calls = make_client(handler)
    adapter = make_adapter(client)
    fixtures = adapter.list_fixtures(
        "nfl",
        2026,
        start_after=datetime(2026, 8, 1, tzinfo=UTC),
        start_before=datetime(2026, 9, 15, tzinfo=UTC),
    )
    sea = next(f for f in fixtures if f.vendor_fixture_id == SEA_NE_ID)
    assert sea.raw is events[0] or sea.raw == events[0]
    assert sea.start_date == datetime(2026, 9, 7, 20, 20, tzinfo=UTC)
    assert sea.start_date.tzinfo is not None
    assert sea.venue_neutral is None
    assert sea.vendor == VENDOR
    assert sea.season_year == 2026
    assert sea.vendor_season_week is None

    pre = next(f for f in fixtures if f.vendor_fixture_id == PRESEASON_ID)
    assert pre.season_type == "Preseason"
    assert pre.venue_neutral is None

    quotes = adapter.get_odds([SEA_NE_ID], [], FEATURED)
    under = next(
        q
        for q in quotes
        if q.market_id == "totals"
        and q.selection == "Under"
        and q.sportsbook == "fanduel"
    )
    original_under = game_odds[0]["bookmakers"][0]["markets"][2]["outcomes"][1]
    assert under.raw == original_under
    assert under.price_american == -115
    assert under.price_decimal == american_to_decimal(-115)
    assert under.selection_line == "under"
    assert under.points == Decimal("43.5")
    assert under.is_main is True
    assert under.availability == "open"
    assert under.vendor_timestamp == datetime(2026, 9, 7, 18, 0, tzinfo=UTC)


def test_neutral_venue_is_not_invented() -> None:
    events = load_json("nfl_events.json")

    def handler(request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if path.endswith("/americanfootball_nfl/events"):
            return json_response(events)
        if path.endswith("/americanfootball_nfl_preseason/events"):
            return json_response([])
        raise AssertionError(f"unexpected {request.url}")

    client, _calls = make_client(handler)
    adapter = make_adapter(client)
    fixtures = adapter.list_fixtures(
        "nfl",
        2026,
        start_after=datetime(2026, 9, 1, tzinfo=UTC),
        start_before=datetime(2026, 9, 15, tzinfo=UTC),
    )
    assert fixtures
    assert all(f.venue_neutral is None for f in fixtures)
    assert all(f.venue_neutral is not True for f in fixtures)


def test_400_raises_vendor_contract_error_without_retry() -> None:
    error_body = load_json("error_400.json")
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(error_body, status=400)

    client, calls = make_client(handler)
    adapter = make_adapter(client, slept=slept)
    with pytest.raises(VendorContractError, match="INVALID_MARKET"):
        adapter.get_odds([SEA_NE_ID], [], FEATURED)
    assert len(calls) == 1
    assert slept == []


def test_500_retries_with_backoff_then_succeeds() -> None:
    game_odds = load_json("nfl_odds_game_markets.json")
    statuses = [500, 200]
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        if status == 500:
            return httpx.Response(500, text="upstream", headers=QUOTA_HEADERS)
        return json_response(game_odds)

    client, calls = make_client(handler)
    adapter = make_adapter(client, slept=slept, max_retries=3, rng=random.Random(0))
    quotes = adapter.get_odds([SEA_NE_ID], [], FEATURED)
    assert quotes
    assert len(calls) == 2
    assert len(slept) == 1
    assert slept[0] > 0


def test_500_exhausted_raises_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream")

    client, calls = make_client(handler)
    adapter = make_adapter(client, max_retries=2)
    with pytest.raises(VendorTransportError):
        adapter.get_odds([SEA_NE_ID], [], FEATURED)
    assert len(calls) == 3


def test_list_markets_empty_without_raising() -> None:
    empty = load_json("nfl_event_markets_empty.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if EMPTY_MARKETS_ID in _path(request) and _path(request).endswith("/markets"):
            return json_response(empty)
        raise AssertionError(f"unexpected {request.url}")

    client, _calls = make_client(handler)
    adapter = make_adapter(client)
    refs = adapter.list_markets(EMPTY_MARKETS_ID, ["draftkings"])
    assert refs == []


def test_list_markets_normalizes_discovered_keys() -> None:
    payload = load_json("nfl_event_markets.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if SEA_NE_ID in _path(request) and _path(request).endswith("/markets"):
            return json_response(payload)
        raise AssertionError(f"unexpected {request.url}")

    client, _calls = make_client(handler)
    adapter = make_adapter(client)
    refs = adapter.list_markets(SEA_NE_ID, [])
    assert [r.market_id for r in refs] == ["h2h", "spreads", "totals"]
    assert refs[0].raw == payload["bookmakers"][0]["markets"][0]
    assert refs[0].sportsbook == "fanduel"


def test_player_props_skipped_when_flag_off() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            f"HTTP must not be called for skipped props, got {request.url}"
        )

    client, calls = make_client(handler)
    adapter = make_adapter(client, include_player_props=False)
    quotes = adapter.get_odds([ATL_ARI_ID], [], ["player_pass_tds"])
    assert quotes == []
    assert calls == []


def test_player_props_fetched_when_flag_on() -> None:
    props = load_json("nfl_odds_player_props.json")

    def handler(request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if ATL_ARI_ID in path and path.endswith("/odds"):
            return json_response(props)
        raise AssertionError(f"unexpected {request.url}")

    client, calls = make_client(handler)
    adapter = make_adapter(client, include_player_props=True)
    quotes = adapter.get_odds([ATL_ARI_ID], [], ["player_pass_tds"])
    assert quotes
    assert all(q.market_id == "player_pass_tds" for q in quotes)
    kirk = next(
        q
        for q in quotes
        if q.vendor_player_id == "Kirk Cousins" and q.selection == "Over"
    )
    assert kirk.raw == props["bookmakers"][0]["markets"][0]["outcomes"][0]
    assert kirk.is_main is False
    assert kirk.selection_line == "over"
    assert len(calls) == 1
    assert "/events/" in _path(calls[0])


def test_props_flag_off_still_fetches_featured_only() -> None:
    game_odds = load_json("nfl_odds_game_markets.json")

    def handler(request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if path.endswith("/americanfootball_nfl/odds") and "/events/" not in path:
            return json_response(game_odds)
        raise AssertionError(f"event-odds must not be called, got {request.url}")

    client, calls = make_client(handler)
    adapter = make_adapter(client, include_player_props=False)
    quotes = adapter.get_odds([SEA_NE_ID], [], ["h2h", "player_pass_tds"])
    assert quotes
    assert all(not q.market_id.startswith("player_") for q in quotes)
    assert len(calls) == 1


def test_get_odds_two_fixture_ids_one_featured_request() -> None:
    game_odds = load_json("nfl_odds_game_markets.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if _path(request).endswith("/americanfootball_nfl/odds"):
            return json_response(game_odds)
        raise AssertionError(f"unexpected {request.url}")

    client, calls = make_client(handler)
    adapter = make_adapter(client)
    quotes = adapter.get_odds([SEA_NE_ID, DAL_CIN_ID], [], FEATURED)
    fixture_ids = {q.vendor_fixture_id for q in quotes}
    assert fixture_ids == {SEA_NE_ID, DAL_CIN_ID}
    assert len(calls) == 1
    assert "eventIds" not in str(calls[0].url)


def test_get_odds_empty_ids_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected {request.url}")

    client, calls = make_client(handler)
    adapter = make_adapter(client)
    assert adapter.get_odds([], [], FEATURED) == []
    assert calls == []


def test_get_results_normalizes_scores() -> None:
    scores = load_json("nfl_scores.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if _path(request).endswith("/scores"):
            return json_response(scores)
        raise AssertionError(f"unexpected {request.url}")

    client, _calls = make_client(handler)
    adapter = make_adapter(client)
    results = adapter.get_results([SEA_NE_ID, DAL_CIN_ID])
    finished = next(r for r in results if r.vendor_fixture_id == SEA_NE_ID)
    assert finished.completed is True
    assert finished.home_score == 24
    assert finished.away_score == 17
    assert finished.raw == scores[0]
    open_game = next(r for r in results if r.vendor_fixture_id == DAL_CIN_ID)
    assert open_game.completed is False
    assert open_game.home_score is None


def test_out_of_usage_credits_maps_to_rate_budget_exceeded() -> None:
    body = load_json("error_out_of_credits.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(body, status=401)

    client, _calls = make_client(handler)
    adapter = make_adapter(client)
    with pytest.raises(RateBudgetExceeded):
        adapter.get_odds([SEA_NE_ID], [], FEATURED)


def test_missing_api_key_raises() -> None:
    with pytest.raises(VendorContractError, match="ODDS_API_KEY"):
        TheOddsApiAdapter(api_key="", sync_quota_on_start=False)
