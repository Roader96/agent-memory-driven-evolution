# Project learnings

## [LRN-20261016-001] best_practice

**Logged**: 2026-10-16T11:38:00+08:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
Archive health must measure retained knowledge and review coverage, not just scheduler exit codes.

### Details
Rebuilding an index solely from currently visible rollouts removes historical
records after source cleanup. Review coverage requirements must be explicit in
the prompt and survive context compaction. Lifetime failure counts can establish
recurrence but cannot establish a worsening failure rate or causal regression.

### Resolution
Merge retained summaries, fail closed on index corruption, back up changed indexes,
record content health, retry missing review coverage once, and expose uncertain
follow-up results without rewriting historical audit records. Regression coverage
is included in the release gate.

Newer Hermes gateways restrict session sources to named surfaces. Batch callers
must use the supported `tool` source, retain component identity in prompt/log
markers, and exclude integration sessions from human-task statistics. CLI errors
may be printed to stdout even when stderr is empty; capture either for diagnosis.

### Metadata
- Source: runtime inspection
- Related Files: scripts/codex_memory.py, scripts/skill_evolution/librarian.py, scripts/skill_evolution/followup.py
- Tags: archival, coverage, observability, outcome-metrics

## [LRN-20261023-001] best_practice

**Logged**: 2026-10-23T18:34:00+08:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
Production identity integrity must be tested independently of happy-path scheduler tests.

### Details
List length is not a safe ID allocator after imports, deletions or non-contiguous historical numbering.
Approval routing must validate the immutable identity, target and stage, and preserve pending user decisions.
Historical metrics require source identity and a real observation window; archived skills and derived reports
must not be interpreted as fresh failures. A failed optional provider call does not prevent the current GPT
session from directly reviewing local evidence.

### Resolution
Added an audited schema migration, atomic allocation and revision checks, guarded approvals,
authoritative event extraction, current Codex evidence snapshots, direct GPT scheduling and offline retrieval.
Release regression coverage includes corrupted ledgers, concurrent writers and stale approval files.
The reference scanner also now requires a filename boundary, avoiding the false file match in a hash method.

### Metadata
- Source: runtime audit and user correction
- Related Files: scripts/skill_evolution/state.py, scripts/skill_evolution/approvals.py, scripts/codex_evolution.py
- Tags: identity, migrations, approvals, evidence, direct-review
