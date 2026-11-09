#!/usr/bin/env python3
"""Local task-level experience and observed use; no model calls or auto-adoption.

Records are append-only revisions in .index/experiences.sqlite3. ``remember``
requires source files containing the supplied quotations. These quotations prove
provenance, not that a claimed outcome is true. Updating an existing memory needs
``expected_revision`` (``parent_revision`` is an alias). A replacement can specify
``supersedes: {memory_id: ..., revision: ...}``; the original remains in history.
``brief`` budgets the human-readable ``text``, and saves a receipt even on a miss.
Feedback is an observation linked to that receipt, never proof of causal benefit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LEVELS = {"user_explicit", "verified_outcome", "unverified"}
STATUSES = {"active", "candidate", "superseded"}
OUTCOMES = {"verified_success", "user_accepted", "failed", "unknown"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _path(home):
    return Path(home) / ".index/experiences.sqlite3"


@contextmanager
def _db(home, write=False):
    path = _path(home)
    if not write and not path.exists():
        yield None
        return
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Create privately before SQLite opens the file (including on first use).
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        path.chmod(0o600)
        conn = sqlite3.connect(str(path), timeout=20, isolation_level=None)
    else:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True,
                               timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        if not write and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='heads'").fetchone() is None:
            # A first failed transaction (or concurrent initialization) can
            # leave an empty SQLite file. Reading it must remain non-mutating.
            yield None
            return
        if write:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS versions (memory_id TEXT NOT NULL, revision INTEGER NOT NULL, record TEXT NOT NULL, PRIMARY KEY(memory_id,revision))")
            conn.execute("CREATE TABLE IF NOT EXISTS heads (memory_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS receipts (receipt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS feedback (feedback_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL, task_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
        yield conn
        if write:
            conn.execute("COMMIT")
    except Exception:
        if write and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _heads(conn):
    if conn is None:
        return []
    return [json.loads(row[0]) for row in conn.execute(
        "SELECT v.record FROM versions v JOIN heads h USING(memory_id,revision) ORDER BY v.memory_id")]


def load_experiences(memory_home, include_candidates=False):
    """Read current active memories; never create storage during retrieval."""
    allowed = {"active", "candidate"} if include_candidates else {"active"}
    with _db(memory_home) as conn:
        return [r for r in _heads(conn) if r["status"] in allowed]


def _strings(value, name):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return "\n".join(x.strip() for x in value if x.strip())
    raise ValueError(name + " must be text or a list of text")


def _refs(refs, required=True):
    if not isinstance(refs, list) or (required and not refs):
        raise ValueError("evidence_refs must contain actual source quotations")
    unique = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"].strip():
            raise ValueError("Each evidence reference needs a source path")
        quote = ref.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("Each evidence reference needs a nonempty quote")
        path = Path(ref["path"]).expanduser().resolve()
        if not path.is_file() or quote not in path.read_text(encoding="utf-8"):
            raise ValueError("Missing source file or quotation does not match: " + str(path))
        identity = _hash([str(path), quote])
        unique[identity] = {"path": str(path), "quote": quote, "source_id": identity}
    return [unique[k] for k in sorted(unique)]


def _put(conn, record):
    conn.execute("INSERT INTO versions VALUES (?,?,?)",
                 (record["memory_id"], record["revision"], _json(record)))
    conn.execute("INSERT INTO heads VALUES (?,?) ON CONFLICT(memory_id) DO UPDATE SET revision=excluded.revision",
                 (record["memory_id"], record["revision"]))


def remember(memory_home, record):
    if not isinstance(record, dict):
        raise ValueError("Memory input must be an object")
    item = {key: _strings(record.get(key, ""), key) for key in
            ("task_family", "scope", "conditions", "recommended_action", "avoid")}
    if not item["task_family"] or not item["scope"] or not item["recommended_action"]:
        raise ValueError("task_family, scope and recommended_action are required")
    item["evidence_level"] = record.get("evidence_level", "unverified")
    item["status"] = record.get("status", "candidate" if item["evidence_level"] == "unverified" else "active")
    if item["evidence_level"] not in LEVELS or item["status"] not in STATUSES - {"superseded"}:
        raise ValueError("Unsupported evidence level or memory status")
    if item["evidence_level"] == "unverified" and item["status"] != "candidate":
        raise ValueError("Unverified experience can only be a candidate")
    item["evidence_refs"] = _refs(record.get("evidence_refs", []))
    # Evidence is deduplicated, not a numeric confidence score. Repetition is not
    # independent corroboration; source_count counts files, not quotations.
    item["source_count"] = len({r["path"] for r in item["evidence_refs"]})
    identifier = record.get("memory_id") or "mem-" + _hash({k: item[k] for k in
        ("task_family", "scope", "conditions", "recommended_action", "avoid")})[:20]
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", identifier):
        raise ValueError("Invalid memory_id")
    item["memory_id"] = identifier
    expected = record.get("expected_revision", record.get("parent_revision"))
    with _db(memory_home, write=True) as conn:
        heads = {r["memory_id"]: r for r in _heads(conn)}
        old = heads.get(identifier)
        if old is not None:
            identical = all(old.get(k) == v for k, v in item.items())
            if identical and expected in (None, old["revision"], old.get("parent_revision")):
                return old  # Retrying an already-applied revision is idempotent.
            if expected != old["revision"]:
                raise ValueError("Missing or stale expected_revision")
            if old["status"] == "superseded":
                raise ValueError("Superseded memories cannot be revived implicitly")
        elif expected not in (None, 0):
            raise ValueError("Parent revision does not exist")
        item["revision"] = old["revision"] + 1 if old else 1
        item["parent_revision"] = old["revision"] if old else None
        replacement = record.get("supersedes")
        if replacement:
            if old or item["status"] != "active":
                raise ValueError("A superseding memory must be a new active identity")
            if isinstance(replacement, str):
                replacement = {"memory_id": replacement, "revision": record.get("supersedes_revision")}
            if not isinstance(replacement, dict):
                raise ValueError("supersedes needs memory_id and revision")
            parent = heads.get(replacement.get("memory_id"))
            if not parent or parent["revision"] != replacement.get("revision") or parent["status"] == "superseded":
                raise ValueError("Missing or stale supersedes parent revision")
            if parent["scope"] != item["scope"] or parent["task_family"] != item["task_family"]:
                raise ValueError("Replacement must preserve parent scope and task family")
            changed = dict(parent, status="superseded", revision=parent["revision"] + 1,
                           parent_revision=parent["revision"], superseded_by=identifier, updated_at=_now())
            _put(conn, changed)
            item["supersedes"] = {"memory_id": parent["memory_id"], "revision": parent["revision"]}
        item["updated_at"] = _now()
        _put(conn, item)
        return item


def _terms(value):
    value = value.lower()
    result = set(re.findall(r"[a-z0-9_-]{2,}", value))
    for run in re.findall(r"[\u4e00-\u9fff]+", value):
        result.update(run[i:i+2] for i in range(len(run)-1))
        if len(run) == 1:
            result.add(run)
    return result


def _observations(memory_home, item):
    with _db(memory_home) as conn:
        rows = [] if conn is None else [json.loads(r[0]) for r in conn.execute(
            "SELECT payload FROM feedback ORDER BY rowid")]
    selected = [r for r in rows if r.get("revisions", {}).get(item["memory_id"]) == item["revision"]
                and item["memory_id"] in r.get("applied_memory_ids", [])]
    corrections = []
    for row in reversed(selected):
        for text in row["user_corrections"]:
            if text not in corrections:
                corrections.append(text[:160])
    return {"applied_tasks": len({r["task_id"] for r in selected}),
            "outcome_observations": {s: sum(r["outcome_status"] == s for r in selected) for s in sorted(OUTCOMES)},
            "recent_user_corrections": corrections[:3],
            "interpretation": "Reported observations for this revision, not causal benefit."}


def brief(memory_home, query, family="", project="", task_id="", max_chars=2400, limit=5):
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("A task_id is required to bind retrieval and feedback")
    if not isinstance(max_chars, int) or max_chars < 0 or limit < 1:
        raise ValueError("Invalid character budget or result limit")
    terms = _terms(query)
    ranked, warnings = [], []
    for item in load_experiences(memory_home):
        if item["scope"] != "global" and item["scope"] != project:
            continue
        if family and item["task_family"] != family:
            continue
        if not query.strip() and not family:
            continue  # Project membership alone is not task relevance.
        overlap = terms & _terms(" ".join(item[k] for k in
            ("conditions", "recommended_action", "avoid", "task_family")))
        if query.strip() and not overlap:
            continue
        try:
            _refs(item["evidence_refs"])
        except (ValueError, OSError) as exc:
            warnings.append({"memory_id": item["memory_id"], "revision": item["revision"],
                             "reason": str(exc)[:300]})
            continue
        score = len(overlap) / max(1, len(terms)) + (0.1 if item["scope"] == project else 0)
        ranked.append((score, item))
    ranked.sort(key=lambda row: (-row[0], row[1]["memory_id"]))
    chosen, chunks, size = [], [], 0
    for score, item in ranked:
        item = {**item, "use_observations": _observations(memory_home, item)}
        observation = item["use_observations"]
        counts = observation["outcome_observations"]
        feedback_text = (f"Reported use of this revision: {observation['applied_tasks']} tasks; "
                         f"unknown={counts['unknown']}, failed={counts['failed']}, "
                         f"verified_success={counts['verified_success']}, user_accepted={counts['user_accepted']}; "
                         "not causal evidence.\nRecent user corrections: "
                         + (" | ".join(observation["recent_user_corrections"]) or "none recorded"))
        sources = "\n".join(r["path"] + " :: " + r["quote"][:180] for r in item["evidence_refs"])
        chunk = (f"[{item['memory_id']} r{item['revision']}] {item['task_family']} / {item['scope']}\n"
                 f"Conditions: {item['conditions']}\nDo: {item['recommended_action']}\n"
                 f"Avoid: {item['avoid']}\nEvidence ({item['evidence_level']}): {sources}\n{feedback_text}")
        if size + len(chunk) + (2 if chunks else 0) > max_chars:
            continue
        chosen.append(item)
        chunks.append(chunk)
        size += len(chunk) + (2 if len(chunks) > 1 else 0)
        if len(chosen) >= limit:
            break
    receipt = {"receipt_id": "rec-" + uuid.uuid4().hex, "task_id": task_id,
               "created_at": _now(), "query": query, "family": family, "project": project,
               "retrieved_ids": [r["memory_id"] for r in chosen],
               "revisions": {r["memory_id"]: r["revision"] for r in chosen},
               "snapshots": {r["memory_id"]: r for r in chosen},
               "evidence_warnings": warnings,
               "adoption": "not_observed", "max_chars": max_chars}
    with _db(memory_home, write=True) as conn:
        conn.execute("INSERT INTO receipts VALUES (?,?,?,?)", (receipt["receipt_id"], task_id,
                     receipt["created_at"], _json(receipt)))
    return {**receipt, "retrieved": chosen, "text": "\n\n".join(chunks)}


def _list_of_text(value, name):
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(name + " must be a list of text")
    return sorted(set(x.strip() for x in value if x.strip()))


def feedback(memory_home, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("task_id"), str) or not payload["task_id"].strip():
        raise ValueError("Feedback requires task_id")
    outcome = payload.get("outcome_status", "unknown")
    if outcome not in OUTCOMES:
        raise ValueError("Unsupported outcome status")
    actions = _list_of_text(payload.get("observed_actions", []), "observed_actions")
    corrections = _list_of_text(payload.get("user_corrections", []), "user_corrections")
    applied = _list_of_text(payload.get("applied_memory_ids", []), "applied_memory_ids")
    if applied and not actions:
        raise ValueError("Applied memories need an explicit observation of actions")
    refs = _refs(payload.get("evidence_refs", []), required=outcome != "unknown" or bool(corrections))
    if any(not any(text in ref["quote"] for ref in refs) for text in corrections):
        raise ValueError("User corrections must quote the supplied source evidence")
    # Do not create an empty database for an invalid feedback request.
    if not _path(memory_home).exists():
        raise ValueError("No retrieval receipt exists for this task")
    with _db(memory_home, write=True) as conn:
        if payload.get("receipt_id"):
            row = conn.execute("SELECT payload FROM receipts WHERE receipt_id=? AND task_id=?",
                               (payload["receipt_id"], payload["task_id"])).fetchone()
        else:
            row = conn.execute("SELECT payload FROM receipts WHERE task_id=? ORDER BY rowid DESC LIMIT 1",
                               (payload["task_id"],)).fetchone()
        if row is None:
            raise ValueError("Feedback must reference a retrieval receipt for the same task")
        receipt = json.loads(row[0])
        if not set(applied) <= set(receipt["retrieved_ids"]):
            raise ValueError("Applied memories must be a subset of this receipt's retrieval")
        observation = {"task_id": payload["task_id"], "receipt_id": receipt["receipt_id"],
                       "applied_memory_ids": applied, "revisions": {i: receipt["revisions"][i] for i in applied},
                       "applied_snapshots": {i: receipt["snapshots"][i] for i in applied},
                       "outcome_status": outcome, "observed_actions": actions,
                       "user_corrections": corrections, "evidence_refs": refs}
        feedback_id = "fb-" + _hash(observation)
        prior = conn.execute("SELECT payload FROM feedback WHERE feedback_id=?", (feedback_id,)).fetchone()
        if prior:
            return {**json.loads(prior[0]), "duplicate": True}
        observation.update(feedback_id=feedback_id, created_at=_now())
        conn.execute("INSERT INTO feedback VALUES (?,?,?,?,?)", (feedback_id, receipt["receipt_id"],
                     payload["task_id"], observation["created_at"], _json(observation)))
        return {**observation, "duplicate": False}


def stats(memory_home):
    with _db(memory_home) as conn:
        receipts = [] if conn is None else [json.loads(r[0]) for r in conn.execute("SELECT payload FROM receipts")]
        observations = [] if conn is None else [json.loads(r[0]) for r in conn.execute("SELECT payload FROM feedback ORDER BY rowid")]
        memories = _heads(conn)
    latest = {r["task_id"]: r for r in observations}
    latest_counts = {s: sum(r["outcome_status"] == s for r in latest.values()) for s in sorted(OUTCOMES)}
    uses = {(r["task_id"], i) for r in observations for i in r["applied_memory_ids"]}
    counts = {s: len({r["task_id"] for r in observations if r["outcome_status"] == s}) for s in sorted(OUTCOMES)}
    return {"active_memories": sum(r["status"] == "active" for r in memories),
            "candidate_memories": sum(r["status"] == "candidate" for r in memories),
            "retrieval_receipts": len(receipts), "retrieval_tasks": len({r["task_id"] for r in receipts}),
            "retrieved_memory_uses": len({(r["task_id"], i) for r in receipts for i in r["retrieved_ids"]}),
            "applied_memory_uses": len(uses), "applied_tasks": len({task for task, _ in uses}),
            "feedback_observations": len(observations), "outcome_task_counts": counts,
            "accepted_tasks": len({r["task_id"] for r in observations if r["outcome_status"] in {"verified_success", "user_accepted"}}),
            "ever_accepted_tasks": len({r["task_id"] for r in observations if r["outcome_status"] in {"verified_success", "user_accepted"}}),
            "latest_outcome_task_counts": latest_counts,
            "latest_accepted_tasks": latest_counts["verified_success"] + latest_counts["user_accepted"],
            "tasks_without_feedback": len({r["task_id"] for r in receipts} - {r["task_id"] for r in observations}),
            "interpretation": "Observed reports only, not causal benefit. accepted_tasks is a legacy alias of ever_accepted_tasks, not current success. Historical outcome counts may overlap; latest counts use the most recent report per task. Unknown and missing feedback are not success."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("remember", "brief", "feedback", "stats"):
        p = sub.add_parser(command)
        p.add_argument("--memory-home", type=Path, default=Path(os.environ.get("CODEX_MEMORY_HOME", str(Path.home()/"CodexMemory"))))
        if command in {"remember", "feedback"}:
            p.add_argument("--input", type=Path, required=True, help="UTF-8 JSON input file")
        if command == "brief":
            p.add_argument("--query", default="")
            p.add_argument("--family", default="")
            p.add_argument("--project", default="")
            p.add_argument("--task-id", required=True)
            p.add_argument("--max-chars", type=int, default=2400)
            p.add_argument("--limit", type=int, default=5)
            p.add_argument("--full", action="store_true", help="Include complete frozen memory snapshots in JSON")
    args = parser.parse_args(argv)
    try:
        if args.command in {"remember", "feedback"}:
            data = json.loads(args.input.read_text(encoding="utf-8"))
            result = (remember if args.command == "remember" else feedback)(args.memory_home, data)
        elif args.command == "brief":
            result = brief(args.memory_home, args.query, args.family, args.project,
                           args.task_id, args.max_chars, args.limit)
            if not args.full:
                result = {k: v for k, v in result.items() if k not in {"snapshots", "retrieved"}}
        else:
            result = stats(args.memory_home)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
