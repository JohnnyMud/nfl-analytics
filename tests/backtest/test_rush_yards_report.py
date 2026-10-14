"""Report formatting renders missing metrics as a dash, never as zero."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from backtest.rush_yards_report import (
    MetricLine,
    RunSummary,
    RushReport,
    format_report,
    format_runs,
)

RUN = uuid4()


def _run(*, has_metrics: bool) -> RunSummary:
    return RunSummary(
        run_id=RUN,
        predicted_at=datetime(2026, 10, 14, 21, 0, tzinfo=UTC),
        model_versions="xgb_rush_rb_v1+pregame_safe",
        feature_set_version="rush_rb_v1",
        first_season=2026,
        last_season=2026,
        n_predictions=4,
        n_labeled=0,
        has_metrics=has_metrics,
    )


def test_unlabeled_live_metric_renders_dash() -> None:
    report = RushReport(
        runs=[_run(has_metrics=False)],
        metrics=[
            MetricLine(
                run_id=RUN,
                model_name="xgboost",
                model_version="xgb_rush_rb_v1+pregame_safe",
                season=None,
                mae=None,
                rmse=None,
                n=0,
                n_unknown=0,
                n_unlabeled=4,
                source="live",
            )
        ],
        common=[],
    )

    text = format_report(report)

    assert "live labels" in text
    assert " 0.00" not in text
    assert "     -" in text
    assert "common rows: none" in text


def test_empty_run_list() -> None:
    assert format_runs([]) == "no stored runs"
