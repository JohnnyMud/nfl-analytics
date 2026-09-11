"""CLI entrypoint: ``python -m ingest.odds tick|loop``."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from common.env import database_url, load_dotenv
from common.logging import configure_logging, get_logger
from ingest.odds.config import CaptureConfig
from ingest.odds.orchestrator import Orchestrator, TickStats
from ingest.odds.the_odds_api import TheOddsApiAdapter

_log = get_logger("ingest.odds.cli")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m ingest.odds")
    sub = parser.add_subparsers(dest="command", required=True)

    tick = sub.add_parser("tick", help="run one capture cycle")
    tick.add_argument(
        "--dry-run",
        action="store_true",
        help="print the due plan; no odds fetch and no writes",
    )
    sub.add_parser("loop", help="run capture cycles until interrupted")

    args = parser.parse_args(argv)
    if args.command == "tick":
        return _cmd_tick(dry_run=args.dry_run)
    if args.command == "loop":
        return _cmd_loop()
    parser.error(f"unknown command {args.command}")
    return 2


def _cmd_tick(*, dry_run: bool) -> int:
    url = _require_database_url()
    if url is None:
        return 1
    config = CaptureConfig.from_env()
    engine = create_engine(url)
    try:
        with TheOddsApiAdapter(
            monthly_credit_budget=config.monthly_credit_budget,
        ) as provider:
            orch = Orchestrator(engine, provider, config)
            stats = orch.run_tick(datetime.now(UTC), dry_run=dry_run)
            _emit_plan(stats)
            return 0
    finally:
        engine.dispose()


def _cmd_loop() -> int:
    url = _require_database_url()
    if url is None:
        return 1
    config = CaptureConfig.from_env()
    engine: Engine = create_engine(url)
    interval = config.tick_interval.total_seconds()
    try:
        with TheOddsApiAdapter(
            monthly_credit_budget=config.monthly_credit_budget,
        ) as provider:
            orch = Orchestrator(engine, provider, config)
            while True:
                stats = orch.run_tick(datetime.now(UTC))
                _emit_plan(stats)
                time.sleep(interval)
    except KeyboardInterrupt:
        _log.info("loop_stopped")
        return 0
    finally:
        engine.dispose()


def _require_database_url() -> str | None:
    url = database_url()
    if not url:
        _log.error("DATABASE_URL is missing")
        return None
    return url


def _emit_plan(stats: TickStats) -> None:
    for plan in stats.fixtures:
        _log.info(
            "fixture_plan",
            vendor_fixture_id=plan.vendor_fixture_id,
            kickoff_at=plan.kickoff_at.isoformat(),
            cadence_tier=plan.cadence_tier.value,
            effective_tier=plan.effective_tier.value,
            due=plan.due,
        )


if __name__ == "__main__":
    sys.exit(main())
