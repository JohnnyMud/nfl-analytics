"""Unit tests for ``common.env`` — no network, no secrets."""

from __future__ import annotations

import os
from pathlib import Path

from common.env import load_dotenv


def test_load_dotenv_sets_missing_keys(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'ODDS_API_KEY="test-key"\nDATABASE_URL="postgresql://postgres:postgres@localhost:5432/nfl_analytics"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    loaded = load_dotenv(env_file)

    assert loaded == env_file
    assert os.environ["ODDS_API_KEY"] == "test-key"
    assert os.environ["DATABASE_URL"] == (
        "postgresql://postgres:postgres@localhost:5432/nfl_analytics"
    )


def test_load_dotenv_does_not_override_existing(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ODDS_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ODDS_API_KEY", "from-process")

    load_dotenv(env_file)

    assert os.environ["ODDS_API_KEY"] == "from-process"


def test_load_dotenv_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / "missing.env") is None
