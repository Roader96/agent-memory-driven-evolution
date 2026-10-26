#!/usr/bin/env python3
"""Persist alert fingerprints; a failed delivery must never count as delivered."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path


def _plan(path, message, now=None, cooldown=3600):
    now = time.time() if now is None else now
    data = json.loads(path.read_text()) if path.exists() else {}
    fingerprint = hashlib.sha256(message.encode()).hexdigest()
    if data.get("delivered_fingerprint") == fingerprint:
        return False
    if data.get("attempt_fingerprint") == fingerprint and now - data.get("attempt_at", 0) < cooldown:
        return False
    data.update(attempt_fingerprint=fingerprint, attempt_at=now, message=message)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
    return True


def _ack(path, delivered):
    data = json.loads(path.read_text())
    data["delivery_ok"] = delivered
    if delivered:
        data["delivered_fingerprint"] = data["attempt_fingerprint"]
        data["delivered_at"] = time.time()
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _locked(path, action):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return action()
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def plan(path, message, now=None, cooldown=3600):
    return _locked(path, lambda:_plan(path, message, now, cooldown))


def ack(path, delivered):
    return _locked(path, lambda:_ack(path, delivered))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan", "ack"])
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--message", default="")
    parser.add_argument("--delivered", choices=["0", "1"])
    args = parser.parse_args()
    if args.command == "plan":
        raise SystemExit(0 if plan(args.state, args.message) else 1)
    ack(args.state, args.delivered == "1")
