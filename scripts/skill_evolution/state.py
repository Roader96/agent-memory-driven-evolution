#!/usr/bin/env python3
"""Versioned, atomic proposal ledger with immutable identities and migration audit."""
import copy
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
import paths

HOME = paths.HOME
DIR = paths.HERMES_HOME / "skill_evolution"
STATE_FILE = DIR / "state.json"
LOCK_FILE = DIR / "state.lock"
SCHEMA_VERSION = 2
MAX_PENDING = 13


def empty_state():
    return {"version": SCHEMA_VERSION, "_revision": 0, "weekly_snapshots": [], "follow_ups": [],
            "proposals": [], "preferences": [], "failure_memory": [],
            "prevented": {}, "approved_changes": [], "identity_migration": []}


def migrate_identities(d):
    """Keep every record; link historical references by old ID AND target."""
    original = copy.deepcopy(d.get("proposals", []))
    reserved = [int(m.group(1)) for p in original
                if (m := re.fullmatch(r"P(\d+)", p.get("id", "")))]
    next_number = max(reserved, default=0) + 1
    seen = set()
    audit = d.setdefault("identity_migration", [])
    for index, p in enumerate(d.get("proposals", [])):
        old_id = p.get("id", "")
        p.setdefault("uid", str(uuid.uuid5(uuid.NAMESPACE_URL,
            "agent-memory:" + json.dumps(original[index], sort_keys=True, ensure_ascii=False) + f":{index}")))
        if old_id in seen or not re.fullmatch(r"P\d+", old_id):
            p["legacy_id"] = old_id
            p["id"] = f"P{next_number:03d}"
            next_number += 1
            audit.append({"old_id": old_id, "new_id": p["id"], "uid": p["uid"],
                          "target": p.get("target"), "reason": "duplicate_or_invalid_id"})
        seen.add(p["id"])
    for collection, field in (("follow_ups", "proposal_id"), ("approved_changes", "id")):
        for record in d.get(collection, []):
            old_id = record.get(field)
            candidates = [p for before, p in zip(original, d["proposals"])
                          if before.get("id") == old_id
                          and (not record.get("target") or p.get("target") == record["target"])
                          and (not record.get("kind") or p.get("kind") == record["kind"])]
            if collection == "follow_ups":
                candidates = [p for p in candidates if p.get("status") == "done"]
            if len(candidates) == 1:
                p = candidates[0]
                record["legacy_proposal_id"] = old_id
                record[field] = p["id"]
                record["proposal_uid"] = p["uid"]
                record["link_status"] = "verified"
            else:
                record["link_status"] = "unresolved"
                if collection == "follow_ups":
                    record["legacy_result"] = record.get("result")
                    record["result"] = "inconclusive"
                    record["result_detail"] = "Historical identity is ambiguous; excluded from automatic attribution"
    return d


_MIGRATIONS = {1: migrate_identities}


def _migrate(d, from_v):
    v = from_v
    while v < SCHEMA_VERSION:
        fn = _MIGRATIONS.get(v)
        if fn is None:
            raise RuntimeError(f"No state migration v{v} -> {v+1}")
        backup = STATE_FILE.with_suffix(f".json.bak-v{v}")
        if not backup.exists():
            backup.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            backup.chmod(0o600)
        d = fn(d)
        v += 1
        d["version"] = v
    return d


def _locked(mode):
    import contextlib
    import fcntl
    @contextlib.contextmanager
    def ctx():
        DIR.mkdir(parents=True, exist_ok=True)
        with open(LOCK_FILE, "a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH if mode == "sh" else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return ctx()


def validate(d):
    ids = [p.get("id") for p in d.get("proposals", [])]
    if len(ids) != len(set(ids)) or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError("Duplicate or invalid proposal ID; refusing ambiguous state")
    uids = [p["uid"] for p in d.get("proposals", []) if p.get("uid")]
    if len(uids) != len(ids) or any(not isinstance(uid, str) for uid in uids) or len(uids) != len(set(uids)):
        raise ValueError("Missing or duplicate proposal UID")
    by_id = {p["id"]: p for p in d.get("proposals", [])}
    for f in d.get("follow_ups", []):
        if f.get("link_status") == "unresolved":
            continue
        p = by_id.get(f.get("proposal_id"))
        if not p or p.get("target") != f.get("target"):
            raise ValueError("Follow-up target does not match proposal identity")
        if p.get("uid") != f.get("proposal_uid"):
            raise ValueError("Follow-up UID mismatch")


def _read():
    if not STATE_FILE.exists():
        return empty_state()
    d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or d.get("version", 1) > SCHEMA_VERSION:
        raise ValueError("Unsupported state schema")
    d.setdefault("version", 1)
    for key, value in empty_state().items():
        d.setdefault(key, copy.deepcopy(value))
    return d


def _write(d):
    d["_revision"] = d.get("_revision", 0) + 1
    tmp = STATE_FILE.with_suffix(f".json.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as stream:
            os.chmod(tmp, 0o600)
            stream.write(json.dumps(d, ensure_ascii=False, indent=1))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, STATE_FILE)
    finally:
        if tmp.exists():
            tmp.unlink()


def load():
    # Exclusive only for the short read/migration transaction; no stale migration
    # can overwrite a concurrent approval after dropping a shared lock.
    with _locked("ex"):
        d = _read()
        if d.get("version", 1) < SCHEMA_VERSION:
            d = _migrate(d, d.get("version", 1))
            validate(d)
            _write(d)
        validate(d)
        return d


def save(d):
    with _locked("ex"):
        current = _read()
        if STATE_FILE.exists() and current.get("_revision", 0) != d.get("_revision", 0):
            raise RuntimeError("Concurrent ledger change; reload or use state.update")
        validate(d)
        _write(d)


def update(mutator):
    with _locked("ex"):
        d = _read()
        if d.get("version", 1) < SCHEMA_VERSION:
            d = _migrate(d, d.get("version", 1))
        validate(d)
        mutator(d)
        validate(d)
        _write(d)
        return d


def unique_proposal(d, pid, expected_target=None, expected_uid=None):
    matches = [p for p in d["proposals"] if p.get("id") == pid]
    if len(matches) != 1:
        raise ValueError(f"Proposal {pid} missing or ambiguous")
    p = matches[0]
    if expected_target is not None and p.get("target") != expected_target:
        raise ValueError(f"Stale approval target for {pid}")
    if expected_uid is not None and p.get("uid") != expected_uid:
        raise ValueError(f"Stale approval UID for {pid}")
    return p


def add_snapshot(metrics_facts, global_stats):
    slim = [{"name": x["name"], "load": x["load_sessions"], "self_err": x["self_errors"],
             "reload": x["reload_sessions"], "edits": x["edits"], "disabled": x["disabled"]}
            for x in metrics_facts]
    week = datetime.now().strftime("%Y-%m-%d")
    def mutate(d):
        d["weekly_snapshots"] = [s for s in d["weekly_snapshots"] if s.get("week") != week]
        d["weekly_snapshots"].append({"week": week,
            "n_installed": sum(bool(x["installed"]) for x in metrics_facts),
            "n_used": sum(x["load_sessions"] > 0 for x in metrics_facts),
            "global": global_stats, "skills": slim})
        d["weekly_snapshots"] = d["weekly_snapshots"][-26:]
    return update(mutate)


def add_proposal(p):
    added = False
    def mutate(d):
        nonlocal added
        if any(ex.get("target") == p["target"] and ex.get("kind") == p["kind"]
               and ex.get("status") in ("pending", "approved", "done", "rejected")
               for ex in d["proposals"]):
            return
        if sum(x.get("status") == "pending" for x in d["proposals"]) >= MAX_PENDING:
            return
        maximum = max((int(m.group(1)) for ex in d["proposals"]
                       if (m := re.fullmatch(r"P(\d+)", ex["id"]))), default=0)
        if "id" in p and any(ex["id"] == p["id"] for ex in d["proposals"]):
            raise ValueError("Explicit proposal ID already exists")
        p.setdefault("id", f"P{maximum+1:03d}")
        p.setdefault("uid", str(uuid.uuid4()))
        p.setdefault("status", "pending")
        p.setdefault("created", datetime.now().strftime("%Y-%m-%d"))
        d["proposals"].append(copy.deepcopy(p))
        added = True
    return update(mutate), added


def list_pending():
    return [p for p in load()["proposals"] if p["status"] == "pending"]
