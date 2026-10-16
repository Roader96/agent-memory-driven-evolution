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
