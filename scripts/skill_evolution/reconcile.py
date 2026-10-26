#!/usr/bin/env python3
"""Reconcile legacy evidence without deleting audit history or executing skills."""
from datetime import datetime
import state


def reconcile(facts, active_agent="hermes"):
    by_name = {f["name"].lower(): f for f in facts}
    changes = []
    def mutate(d):
        for p in d["proposals"]:
            if p.get("status") not in ("pending", "approved"):
                continue
            fact = by_name.get(p.get("target", "").lower(), {})
            reason = None
            status = "superseded"
            if active_agent == "codex":
                reason, status = "Legacy Hermes proposal; requires a current Codex evidence baseline", "deferred"
            elif p.get("kind") == "fix_reference" and (fact.get("archived") or not fact.get("recent_self_errors", 0)):
                reason = "Archived or no verified failure in the last 30 days; historical loads are insufficient"
            if reason:
                p.setdefault("status_history", []).append({"at": datetime.now().isoformat(),
                    "from": p["status"], "to": status, "reason": reason})
                p["status"] = status
                p["evidence_status"] = "needs_current_evidence"
                changes.append({"id": p["id"], "uid": p.get("uid"), "target": p["target"], "reason": reason})
        d.setdefault("reconciliations", []).append({"at": datetime.now().isoformat(),
            "active_agent": active_agent, "changes": changes})
    state.update(mutate)
    return changes
