"""JSON structured logging."""

from __future__ import annotations

import logging
from typing import Any

import structlog

_configured = False


def configure_logging() -> None:
    """Render every log record as a single JSON object on stdout."""
    global _configured
    if _configured:
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> Any:
    """Return the process-wide JSON logger, configuring it on first use."""
    configure_logging()
    return structlog.get_logger(name)
