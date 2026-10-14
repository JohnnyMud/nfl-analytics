"""The CLI exposes explicit subcommands; there is no implicit default run."""

from __future__ import annotations

import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "models.rush_yards", *args],
        capture_output=True,
        text=True,
        timeout=30,
        env={"DATABASE_URL": "postgresql+psycopg://u:p@localhost:1/none", "PATH": ""},
    )


def test_help_lists_subcommands() -> None:
    result = _run("--help")
    assert result.returncode == 0
    for command in ("backtest", "predict-upcoming", "prune"):
        assert command in result.stdout


def test_no_subcommand_is_an_error_not_a_run() -> None:
    result = _run()
    assert result.returncode != 0
    assert "required" in result.stderr


def test_backtest_subset_choices_are_registered() -> None:
    result = _run("backtest", "--help")
    assert result.returncode == 0
    assert "pregame_safe" in result.stdout
    assert "--dry-run" in result.stdout
