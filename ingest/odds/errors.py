"""Typed failures for the odds ingest port. Never swallowed by adapters."""

from __future__ import annotations


class VendorContractError(Exception):
    """A 4xx (or malformed payload) that means the request or response is wrong.

    Never retried. Fix the request or treat the payload as a contract break.
    """


class RateBudgetExceeded(Exception):
    """The next vendor call would exhaust the monthly credit budget.

    Raised *before* the HTTP request so the orchestrator can coarsen cadence
    instead of burning the remaining quota or failing as a generic HTTP error.
    """


class VendorTransportError(Exception):
    """Retries on 5xx / 429 (or a transport failure) were exhausted."""
