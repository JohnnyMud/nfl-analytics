"""Unit tests for ``common.settings`` — no network, no secrets."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from common.env import load_dotenv
from common.settings import AppEnvironment, Settings, get_settings


def test_settings_from_process_env_simulates_github_secrets(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres.supabase:secret@db.example.supabase.co:5432/postgres",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ODDS_API_KEY", "from-secret")

    settings = Settings()

    assert settings.app_env is AppEnvironment.PRODUCTION
    assert settings.sqlalchemy_url == (
        "postgresql+psycopg://postgres.supabase:secret@db.example.supabase.co:5432/postgres"
    )
    assert settings.postgres_url == (
        "postgresql://postgres.supabase:secret@db.example.supabase.co:5432/postgres"
    )
    assert settings.odds_api_key is not None
    assert settings.odds_api_key.get_secret_value() == "from-secret"
    assert "secret" not in repr(settings)


def test_settings_from_env_file_simulates_local_dotenv(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=local\n"
        "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nfl_analytics\n"
        "ODDS_API_KEY=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    load_dotenv(env_file)
    settings = Settings()

    assert settings.app_env is AppEnvironment.LOCAL
    assert settings.sqlalchemy_url == (
        "postgresql+psycopg://postgres:postgres@localhost:5432/nfl_analytics"
    )
    assert settings.odds_api_key is not None
    assert settings.odds_api_key.get_secret_value() == "from-file"


def test_process_env_wins_over_env_file(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://from-file/db\nAPP_ENV=local\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-secret/db")
    monkeypatch.setenv("APP_ENV", "production")

    load_dotenv(env_file)
    settings = Settings()

    assert settings.postgres_url == "postgresql://from-secret/db"
    assert settings.app_env is AppEnvironment.PRODUCTION


def test_sqlalchemy_url_keeps_explicit_driver(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/nfl_analytics",
    )
    monkeypatch.setenv("APP_ENV", "local")

    settings = Settings()

    assert settings.sqlalchemy_url == (
        "postgresql+psycopg://postgres:postgres@localhost:5432/nfl_analytics"
    )
    assert settings.postgres_url == (
        "postgresql://postgres:postgres@localhost:5432/nfl_analytics"
    )


def test_missing_database_url_raises(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_missing_database_url_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr("common.settings.load_dotenv", lambda path=None: None)
    with pytest.raises(RuntimeError, match="SUPABASE_URL or DATABASE_URL is not set"):
        get_settings()


def test_get_settings_prefers_supabase_url_over_dotenv_database_url(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=local\n"
        "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nfl_analytics\n"
        "SUPABASE_URL=postgresql://postgres.example:secret@aws-0-us-west-1.pooler.supabase.com:5432/postgres\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(
        "common.settings.load_dotenv", lambda path=None: load_dotenv(env_file)
    )

    settings = get_settings()

    assert settings.sqlalchemy_url == (
        "postgresql+psycopg://postgres.example:secret@aws-0-us-west-1.pooler.supabase.com:5432/postgres"
    )


def test_process_database_url_wins_over_supabase_url(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=local\n"
        "SUPABASE_URL=postgresql://postgres.example:secret@aws-0-us-west-1.pooler.supabase.com:5432/postgres\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-process/db")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(
        "common.settings.load_dotenv", lambda path=None: load_dotenv(env_file)
    )

    settings = get_settings()

    assert settings.postgres_url == "postgresql://from-process/db"


def test_production_rejects_localhost(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/nfl_analytics",
    )
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValidationError, match="must not point at localhost"):
        Settings()


def test_app_env_defaults_to_local(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/nfl_analytics",
    )
    monkeypatch.delenv("APP_ENV", raising=False)

    assert Settings().app_env is AppEnvironment.LOCAL


def test_get_settings_reads_app_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/nfl_analytics",
    )
    monkeypatch.setenv("APP_ENV", "ci")

    settings = get_settings()

    assert settings.app_env is AppEnvironment.CI
