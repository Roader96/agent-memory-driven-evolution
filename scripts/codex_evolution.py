#!/usr/bin/env python3
"""Prepare local evidence and record a direct GPT review, without an LLM API."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sqlite3
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


def plugin_config(path):
    """Read discovery fields on Python 3.9 too, without a TOML dependency.

    Older runtimes accept named plugin/marketplace tables with scalar strings
    and booleans. Unsupported discovery syntax is reported in the packet.
    """
    if not path.exists():
        return {}, []
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:
        tomllib = None
    if tomllib is not None:
        try:
            return tomllib.loads(text), []
        except ValueError as exc:
            return {}, [f"Cannot parse plugin configuration: {exc}"]
    result, warnings, section = {}, [], None
    key_pattern = r'(?:"(?:[^"\\]|\\.)*"|\x27[^\x27]*\x27|[\w-]+)'
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = None
            match = re.fullmatch(r'\[\s*(plugins|marketplaces)\s*\.\s*(' + key_pattern + r')\s*\]\s*(?:#.*)?', line)
            if match:
                group, name = match.groups()
                name = json.loads(name) if name.startswith('"') else name.strip("'")
                section = result.setdefault(group, {}).setdefault(name, {})
            elif re.match(r'\[\s*(plugins|marketplaces)\b', line):
                warnings.append(f"Unsupported plugin table syntax at config line {number}")
            continue
        if section is None:
            if re.match(r'(plugins|marketplaces)\s*=', line):
                warnings.append(f"Unsupported inline discovery config at line {number}")
            continue
        match = re.fullmatch(r'(' + key_pattern + r')\s*=\s*(true|false|"(?:[^"\\]|\\.)*"|\x27[^\x27]*\x27)\s*(?:#.*)?', line)
        if not match:
            warnings.append(f"Unsupported plugin value at config line {number}")
            continue
        key, value = match.groups()
        key = json.loads(key) if key.startswith('"') else key.strip("'")
        section[key] = value[1:-1] if value.startswith("'") else json.loads(value)
    return result, warnings


def active_plugin_root(codex_home, plugin_id, marketplaces):
    """Resolve the source manifest's version instead of choosing newest cache."""
    name, separator, marketplace = plugin_id.rpartition("@")
    if not separator or any(part in ("", ".", "..") or "/" in part or "\\" in part
                            for part in (name, marketplace)):
        raise ValueError("invalid plugin identity")
    source = marketplaces.get(marketplace, {}).get("source")
    source_root = None
    if isinstance(source, str):
        market_root = Path(source).expanduser()
        if not market_root.is_absolute():
            market_root = codex_home / market_root
        catalog = read_json(market_root / ".agents/plugins/marketplace.json", {})
        matches = [p for p in catalog.get("plugins", []) if p.get("name") == name]
        if len(matches) == 1:
            location = matches[0].get("source", {})
            if isinstance(location, dict) and location.get("source") == "local":
                source_root = market_root / location["path"]
    cache = codex_home / "plugins/cache" / marketplace / name
    if source_root is not None:
        manifest = read_json(source_root / ".codex-plugin/plugin.json", {})
        version = manifest.get("version")
        if version:
            if not isinstance(version, str) or version in (".", "..") or "/" in version or "\\" in version:
                raise ValueError("invalid plugin version")
            cached = cache / version
            if cached.is_dir():
                return cached
        if manifest:
            return source_root
    versions = sorted(p for p in cache.iterdir() if p.is_dir()) if cache.exists() else []
    if len(versions) == 1:
        return versions[0]
    raise ValueError("active version cannot be resolved from marketplace or unique cache")


def skill_catalog(codex_home, inventory_path=None):
    skills, seen = [], set()

    def add(root, metadata):
        paths = [root] if root.name == "SKILL.md" else sorted(root.rglob("SKILL.md"))
        for path in paths:
            identity = path.resolve()
            if not path.is_file() or ".archive" in path.parts or identity in seen:
                continue
            seen.add(identity)
            skills.append({"name": path.parent.name, "path": str(path),
                           "source_agent": "codex", "usage_quality": "unknown",
                           "load_sessions": None, **metadata})

    for root in (codex_home / "skills", codex_home.parent / ".agents/skills"):
        add(root, {})
    try:
        config, warnings = plugin_config(codex_home / "config.toml")
    except (OSError, ValueError) as exc:
        return skills, [f"Cannot read plugin configuration: {exc}"]
    plugins = config.get("plugins", {})
    marketplaces = config.get("marketplaces", {})
    if not isinstance(plugins, dict) or not isinstance(marketplaces, dict):
        return skills, warnings + ["Plugin and marketplace configuration must be tables"]
    for plugin_id, settings in sorted(plugins.items()):
        if not isinstance(settings, dict) or settings.get("enabled") is not True:
            continue
        try:
            root = active_plugin_root(codex_home, plugin_id, marketplaces)
            manifest = read_json(root / ".codex-plugin/plugin.json", {})
            if not manifest:
                raise ValueError("plugin manifest missing")
            declared = manifest.get("skills", "./skills")
            locations = [declared] if isinstance(declared, str) else declared
            if not isinstance(locations, list) or not all(isinstance(v, str) for v in locations):
                raise ValueError("unsupported plugin skills declaration")
            for location in locations:
                skill_root = root / location
                if "skills" in manifest and not skill_root.exists():
                    raise ValueError("declared skill location missing")
                add(skill_root, {"plugin_id": plugin_id, "plugin_version": manifest.get("version")})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"{plugin_id}: {exc}")
    if inventory_path is not None:
        try:
            inventory = read_json(inventory_path)
            if not isinstance(inventory, dict) or inventory.get("source") != "current_session_available_skills":
                raise ValueError("current session skill inventory missing or invalid")
            observed = datetime.fromisoformat(inventory["observed_at"])
            age = datetime.now(timezone.utc) - observed
            if age < timedelta(minutes=-5) or age > timedelta(hours=24):
                raise ValueError("session skill inventory expired; refresh from current Available skills")
            paths = inventory["paths"]
            if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                raise ValueError("session skill inventory paths must be a list of strings")
            # Session-provided skills describe effective plugin versions. Keep
            # independently installed personal skills even when names overlap.
            replacements = []
            for value in paths:
                path = Path(value)
                if not path.is_absolute() or path.name != "SKILL.md" or not path.is_file():
                    raise ValueError(f"session skill source unavailable: {value}")
                root = next((p for p in path.parents if (p / ".codex-plugin/plugin.json").is_file()), None)
                if root is None:
                    replacements.append((path, {"catalog_source": "current_session"}))
                    continue
                manifest = read_json(root / ".codex-plugin/plugin.json")
                replacements.append((path, {"plugin_id": manifest["name"] + "@" + root.parent.parent.name,
                    "plugin_version": manifest.get("version"), "catalog_source": "current_session"}))
            effective_plugins = {meta["plugin_id"].split("@")[0] for _, meta in replacements if "plugin_id" in meta}
            skills = [s for s in skills if s.get("plugin_id", "").split("@")[0] not in effective_plugins]
            seen = {Path(s["path"]).resolve() for s in skills}
            for path, metadata in replacements:
                add(path, metadata)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"Session skill coverage incomplete: {exc}")
    return skills, warnings


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
    skills, catalog_warnings = skill_catalog(codex_home, memory_home / ".index/session-skills.json")
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
    try:
        import codex_experience
        experience = {"status": "observed", **codex_experience.stats(memory_home)}
    except ImportError:
        experience = {"status": "not_installed"}
    except (ValueError, OSError, sqlite3.Error) as exc:
        experience = {"status": "error", "detail": str(exc)}
    packet = {"created_at": now.isoformat(), "required_checks": CHECKS,
        "source_agent": "codex", "skill_usage_quality": "unknown",
        "memory_experience": experience,
        "semantic_health": read_json(memory_home / ".index/semantic-health.json", {}),
        "archive_health": read_json(memory_home / ".index/health.json", {}),
        "indexed_sessions": len(rows), "missing_cards": missing,
        "recent_sessions": recent, "skill_catalog": skills,
        "skill_catalog_warnings": catalog_warnings,
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
    insufficient = [item["id"] for item in decisions if item["status"] == "insufficient_data"]
    report = memory_home / "skill-evolution" / f"{now:%Y-%m-%d}-gpt-review.md"
    lines = [f"# GPT 记忆与进化审核 {now:%Y-%m-%d}", "", "审核方式：当前 GPT 会话直接审核本地证据，无外部 LLM API。",
             f"证据快照：{digest}", ""]
    for item in decisions:
        lines += [f"## [{item['id']}] {CHECKS[item['id']]} · {item['status']}", "", item["detail"], ""]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    atomic_json(memory_home / "skill-evolution/review-health.json", {
        "checked_at": now.isoformat(), "status": ("reviewed_with_findings" if findings else
            "reviewed_with_insufficient_data" if insufficient else "ok"),
        "reviewer": "gpt_session", "backend": "codex_direct", "packet_id": digest,
        "insufficient_ids": insufficient,
        "reason": "Insufficient evidence: " + ", ".join(insufficient) if insufficient else "",
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
