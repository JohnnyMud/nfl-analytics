# Architecture Decision Records

One file per decision, numbered sequentially, never edited after acceptance — superseded
by a later ADR instead. This preserves the reasoning trail, which is a large part of what
makes this project readable as a portfolio piece.

## Format

```
# NNNN. Title (imperative, decision-shaped)

Status: Proposed | Accepted | Superseded by ADR-NNNN
Date: YYYY-MM-DD

## Context
The forces at play. What makes this decision non-obvious.

## Decision
What we are doing, stated plainly.

## Consequences
What this buys us, what it costs, what it forecloses.

## Alternatives considered
Each with the reason it lost.
```

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-capture-odds-before-everything-else.md) | Capture odds before everything else | Accepted |
| [0002](0002-immutable-bitemporal-odds-store.md) | Immutable, bitemporal odds store | Accepted |
| [0003](0003-snapshot-cadence-and-market-scope.md) | Tiered snapshot cadence and market scope | Accepted |
| [0004](0004-odds-access-path.md) | Odds access path: prototype vs. production | Accepted |
| 0005 | Postgres as system of record | Proposed |
| 0006 | Point-in-time feature contract | Proposed |
| 0007 | Walk-forward validation protocol | Proposed |
