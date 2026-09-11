"""Load local ``.env`` files without adding a dotenv dependency."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path | None = None) -> Path | None:
    """Populate ``os.environ`` from a ``.env`` file.

    Existing environment variables win. Returns the path that was loaded, or
    ``None`` if no file was found.
    """
    for candidate in _candidate_paths(path):
        if not candidate.is_file():
            continue
        _apply_env_file(candidate)
        return candidate
    return None


def database_url() -> str | None:
    """``DATABASE_URL`` with a psycopg3 driver if the scheme was bare."""
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return None
    return _with_psycopg_driver(raw)


def _candidate_paths(explicit: Path | None) -> list[Path]:
    if explicit is not None:
        return [explicit]
    cwd = (Path.cwd() / ".env").resolve()
    repo = (Path(__file__).resolve().parents[1] / ".env").resolve()
    if cwd == repo:
        return [cwd]
    return [cwd, repo]


def _apply_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _unquote(value.strip())


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _with_psycopg_driver(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url
