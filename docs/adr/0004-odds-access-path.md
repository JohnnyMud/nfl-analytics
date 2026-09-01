# 0004. Odds access path: prototype vs. production

Status: Accepted
Date: 2026-08-20

## Context

Odds are reachable today through a connected OpticOdds integration inside the Perplexity
workspace. That is genuinely useful — it let this design be validated against the live API
contract rather than written from documentation alone, and it confirmed real response
shapes, required parameters, and the fact that market availability varies by fixture and
book.

It is not, however, a production data path for an application the user owns. It is an
interactive assistant tool: it carries a per-task call budget, is intended for bounded
question-answering rather than scheduled bulk capture, and its availability is a property of
the workspace rather than of the platform being built. A pipeline that must run unattended
every two minutes before every kickoff for years cannot depend on it.

There is also a licensing dimension. Redistributing a commercial vendor's odds through a
public website is a different act from analyzing them privately, and the terms differ
accordingly. Since this project starts personal but may become public, the access decision
and the display decision must be separable.

## Decision

Two paths, deliberately separated by an interface.

**Prototype path (now).** Use the workspace OpticOdds integration for schema validation,
market discovery, exploratory analysis, and answering design questions — bounded,
interactive work. It informed this spec and will keep informing modeling decisions.

**Production path (before Week 1).** The scheduled pipeline authenticates with the
project's own vendor credentials, held in the environment and never in the repo. Whether
that is a direct OpticOdds account or an alternative feed is a procurement question, not an
architecture question, because:

**All capture goes through one `OddsProvider` interface.** A narrow port —
`list_fixtures`, `list_markets`, `get_odds`, `get_results` — returning our own normalized
types, with the vendor's raw payload attached. The pipeline, schema, and tests know nothing
about a specific vendor. Swapping or adding a feed means writing one adapter.

Adapters planned: `OpticOddsAdapter` (primary), and a second free-tier adapter for
game-level lines as a cross-check and fallback. Two independent sources on moneyline and
spread is cheap and catches a class of silent single-source corruption that no amount of
internal validation can.

**Display rights are decided separately and late.** Storage and analysis proceed now under
private use. Before anything is published, the vendor's terms are reviewed and the API
gains a per-source `redistributable` flag; endpoints filter on it. Derived values —
no-vig probabilities, model edge, CLV summaries, movement statistics — are treated as
distinct from raw per-book prices, since the former are our analysis and the latter are the
vendor's product.

## Consequences

- Capture never blocks on procurement: the free-tier adapter can start the game-level
  series immediately while credentials are sorted, and the tiered schedule and schema stay
  unchanged when the primary adapter lands.
- The vendor is replaceable without touching the pipeline, which materially de-risks the
  most time-critical component.
- Adapter boundaries add indirection and a normalization layer to maintain — accepted, and
  it doubles as the seam where contract tests live.
- Two sources will sometimes disagree. That is a feature: disagreement beyond tolerance
  raises an alert and both values are retained rather than reconciled away.
- The public-launch question stays open without stalling anything, at the cost of
  remembering to answer it before launch. Tracked as a release gate, not a TODO.

## Alternatives considered

**Build the pipeline directly against the workspace integration.** Fastest to a first
capture, but hardcodes a dependency the deployed product cannot keep, and the rewrite would
land during the season — precisely when the pipeline must not be touched.

**Free odds APIs only.** Adequate for moneyline, spread, and total, and genuinely fine for
game-outcome modeling. But player props at per-book granularity are the most interesting
part of the modeling scope and are largely absent from free tiers. Kept as the fallback
adapter rather than the primary.

**Defer the vendor decision until modeling begins.** Equivalent to not capturing, which
ADR-0001 rules out.
