"""Environment-aware process settings.

Locally, missing values are filled from a ``.env`` file. In CI and production,
GitHub Actions injects the same names as secrets / env vars; those always win.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.env import load_dotenv


class AppEnvironment(StrEnum):
    LOCAL = "local"
    CI = "ci"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed view of process configuration. Secrets never appear in ``repr``."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_ignore_empty=True,
    )

    app_env: AppEnvironment = AppEnvironment.LOCAL
    database_url: SecretStr
    odds_api_key: SecretStr | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def _strip_database_url(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("DATABASE_URL is not set")
            return stripped
        return value

    @model_validator(mode="after")
    def _reject_localhost_in_production(self) -> Self:
        if self.app_env is not AppEnvironment.PRODUCTION:
            return self
        raw = self.database_url.get_secret_value().lower()
        if "@localhost" in raw or "@127.0.0.1" in raw or "@[::1]" in raw:
            raise ValueError(
                "APP_ENV=production DATABASE_URL must not point at localhost"
            )
        return self

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy DSN with the psycopg3 driver if the scheme was bare."""
        return _with_psycopg_driver(self.database_url.get_secret_value())

    @property
    def postgres_url(self) -> str:
        """libpq / ADBC DSN: SQLAlchemy dialects stripped."""
        return _without_sqlalchemy_dialect(self.database_url.get_secret_value())


def get_settings() -> Settings:
    """Load settings from the process environment, filling gaps from ``.env``.

    Not cached: the test harness mutates ``DATABASE_URL`` to point at a throwaway
    database, and Alembic must observe that change.
    """
    load_dotenv()
    try:
        return Settings()
    except ValidationError as exc:
        if _database_url_missing(exc):
            raise RuntimeError("DATABASE_URL is not set") from exc
        raise


def _database_url_missing(exc: ValidationError) -> bool:
    return any(error["loc"] == ("database_url",) for error in exc.errors())


def _with_psycopg_driver(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def _without_sqlalchemy_dialect(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg://")
    if url.startswith("postgres://"):
        return "postgresql://" + url.removeprefix("postgres://")
    return url
