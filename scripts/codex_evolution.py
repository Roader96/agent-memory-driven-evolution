#!/usr/bin/env python3
"""Prepare local evidence and record a direct GPT review, without an LLM API."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHECKS = {"A1": "Archive identity, card completeness and historical retention",
          "A2": "Archive freshness and source coverage",
          "S1": "Proposal identities and historical reference integrity",
          "S2": "Pending queue evidence and approval safety",
          "E1": "Failure evidence provenance, dates and deduplication",
          "G1": "Current Codex skill baseline; unknown usage is not zero usage",
          "R1": "Recall and retrieval integration",
          "M1": "Monitoring, deduplication and scheduler ownership",
          "T1": "Tests and deployed source consistency"}


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def prepare(memory_home, codex_home, legacy_state=None):
    import codex_memory
    rows = list(codex_memory.retained_summaries(memory_home).values())
    old = read_json(legacy_state, {}) if legacy_state else {}
    proposals = old.get("proposals", [])
    by_id = {p["id"]: p for p in proposals}
    mismatches = [f.get("proposal_id") for f in old.get("follow_ups", [])
                  if f.get("link_status") != "unresolved"
                  and (f.get("target") != by_id.get(f.get("proposal_id"), {}).get("target")
                       or (f.get("proposal_uid") and f["proposal_uid"] != by_id.get(f.get("proposal_id"), {}).get("uid")))]
    roots = [codex_home / "skills", codex_home.parent / ".agents/skills"]
    skills = []
    for root in roots:
        if root.exists():
            for path in sorted(root.rglob("SKILL.md")):
                if ".archive" not in path.parts:
                    skills.append({"name": path.parent.name, "path": str(path),
                        "source_agent": "codex", "usage_quality": "unknown", "load_sessions": None})
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=7)).isoformat()
    # ISO timestamps have different offsets: compare parsed instants.
    recent = []
    for row in rows:
        try:
            stamp = datetime.fromisoformat(row.get("updated", ""))
            if stamp.tzinfo and stamp >= now - timedelta(days=7):
                recent.append(row)
        except ValueError:
            pass
    missing = [r["session_id"] for r in rows if not (memory_home / (codex_memory.card_relpath(r) + ".md")).exists()]
    packet = {"created_at": now.isoformat(), "required_checks": CHECKS,
        "source_agent": "codex", "skill_usage_quality": "unknown",
        "archive_health": read_json(memory_home / ".index/health.json", {}),
        "indexed_sessions": len(rows), "missing_cards": missing,
        "recent_sessions": recent, "skill_catalog": skills,
        "legacy_ledger": {"path": str(legacy_state) if legacy_state else None,
            "source_agent": "hermes_legacy", "proposal_count": len(proposals),
            "duplicate_ids": len(proposals) - len(by_id), "mismatched_links": mismatches,
            "unresolved_links": sum(f.get("link_status") == "unresolved" for f in old.get("follow_ups", [])),
            "pending": [p for p in proposals if p.get("status") == "pending"]}}
    packet["packet_id"] = hashlib.sha256(json.dumps(packet, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = memory_home / "skill-evolution/evidence" / (now.strftime("%Y-%m-%dT%H%M%S") + "-codex.json")
    atomic_json(path, packet)
    return path


def complete(memory_home, packet_path, result_path):
    packet = read_json(packet_path)
    digest = packet.pop("packet_id")
    if hashlib.sha256(json.dumps(packet, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != digest:
        raise ValueError("Evidence packet modified after preparation")
    result = read_json(result_path)
    if result.get("packet_id") != digest or result.get("reviewer") != "gpt_session":
        raise ValueError("Review must reference this evidence snapshot and the GPT session reviewer")
    decisions = result.get("checks", [])
    indexed = {item["id"]: item for item in decisions}
    if len(indexed) != len(decisions) or set(indexed) != set(CHECKS):
        raise ValueError("Missing, duplicate or unknown review coverage IDs")
    for item in decisions:
        if item.get("status") not in ("pass", "finding", "insufficient_data", "not_applicable") or len(item.get("detail", "")) < 20:
            raise ValueError("Every check needs a supported decision and an explanation")
    now = datetime.now().astimezone()
    findings = sum(item["status"] == "finding" for item in decisions)
    report = memory_home / "skill-evolution" / f"{now:%Y-%m-%d}-gpt-review.md"
    lines = [f"# GPT 记忆与进化审核 {now:%Y-%m-%d}", "", "审核方式：当前 GPT 会话直接审核本地证据，无外部 LLM API。",
             f"证据快照：{digest}", ""]
    for item in decisions:
        lines += [f"## [{item['id']}] {CHECKS[item['id']]} · {item['status']}", "", item["detail"], ""]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    atomic_json(memory_home / "skill-evolution/review-health.json", {
        "checked_at": now.isoformat(), "status": "reviewed_with_findings" if findings else "ok",
        "reviewer": "gpt_session", "backend": "codex_direct", "packet_id": digest,
        "covered_ids": sorted(indexed), "findings_count": findings, "report": str(report)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "complete"])
    parser.add_argument("--memory-home", type=Path, default=Path(os.environ.get("CODEX_MEMORY_HOME", str(Path.home()/"CodexMemory"))))
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex"))))
    parser.add_argument("--legacy-state", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare(args.memory_home, args.codex_home, args.legacy_state))
    else:
        if not args.packet or not args.result:
            parser.error("complete requires --packet and --result")
        print(complete(args.memory_home, args.packet, args.result))


if __name__ == "__main__":
    main()
