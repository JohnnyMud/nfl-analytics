# Agent briefs

Paste-ready task prompts for coding-agent sessions. One file per task. Each brief names the
documents the agent should read, states the deliverable, and defines done.

## How to use agents on this repo

**Ambient context vs. task context.** `AGENTS.md` and `.cursor/rules/` load automatically —
keep them short and rule-dense. Full specs are *referenced*, not pasted. An agent given
2,000 lines of design docs as ambient context follows them worse than one given 100 lines of
hard rules plus a pointer to the relevant spec.

**One task per session.** Start a new session per brief. Long sessions drift: the agent
gradually loses the invariants and starts optimizing for whatever was discussed most
recently. When output quality drops, restart rather than argue.

**Ask for the plan first.** Have the agent restate the task, list files it will create, and
name which invariant its change could violate — before it writes code. Cheapest possible
place to catch a misunderstanding.

**Never accept the capture path on trust.** For anything under `ingest/`, read the diff
yourself. This is the code whose bugs cost data permanently, and it is exactly the kind of
code that looks correct while silently dropping rows.

**Make the agent write the failure test first.** These specs are mostly about failure modes.
If the agent writes happy-path tests only, the interesting behavior is unverified.

## Briefs

| Brief | Task | Status |
| --- | --- | --- |
| [01-repo-foundation.md](01-repo-foundation.md) | Skeleton, tooling, CI, migrations | Ready |
| [02-odds-provider-adapter.md](02-odds-provider-adapter.md) | Vendor port + adapter + recorded fixtures | Ready |
| [03-capture-writer.md](03-capture-writer.md) | Snapshot lifecycle + change-only writer | Ready |
| [04-orchestrator-scheduler.md](04-orchestrator-scheduler.md) | Tiered-cadence orchestrator + minimal scheduler | Ready |
