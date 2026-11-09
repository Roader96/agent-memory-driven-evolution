#!/usr/bin/env python3
"""Offline E5 retrieval over provenance-labelled memory units, not whole logs.

Similarity and source labels aid retrieval; neither proves a claim or a skill's
benefit. Raw session summaries remain in the durable archive unchanged.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

INDEX_SCHEMA_VERSION = 2
EMBEDDING_POLICY = "e5-memory-units-v1-mask-mean-l2-512"
MAX_UNIT_CHARS = 640
MAX_UNITS_PER_SESSION = 40
MAX_SEARCH_RESULTS = 20
DEFAULT_MIN_SIMILARITY = 0.72  # A tunable heuristic, not a calibrated relevance guarantee.
UNIT_FIELDS = (("corrections", "correction", "user_correction_candidate"),
               ("decisions", "decision", "extracted_decision_unverified"),
               ("verified", "verified", "tool_output_signal_not_task_success"),
               ("goal", "goal", "user_request"),
               ("open_items", "open_item", "unresolved_candidate"),
               ("claims", "claim_unverified", "assistant_claim_unverified"))
KIND_PRIORITY = {"correction": 0.035, "verified": 0.025, "decision": 0.015,
                 "experience": 0.02, "claim_unverified": -0.06}


def _compact(value, limit=MAX_UNIT_CHARS):
    import codex_memory
    if isinstance(value, (dict, list)):
        value = codex_memory.text_from_value(value)
    return codex_memory.recall_excerpt(value, limit)


def document(row):
    """E5 passage text. Legacy summary callers remain supported.

    The index calls this once per unit, keeping a late correction independent
    from long preceding logs. The legacy aggregate view is bounded and also
    labels assistant claims; it is not used to encode entire sessions.
    """
    if "unit_kind" in row:
        return ("passage: " + str(row["unit_kind"]) + " [" + str(row.get("evidence_level", "unknown"))
                + "]\n" + _compact(row.get("text", ""))
                + "\nProject: " + _compact(row.get("project", ""), 100)
                + "\nTask: " + _compact(row.get("title", ""), 140))
    parts = [_compact(row.get("title", ""), 140), _compact(row.get("project", ""), 100)]
    for field, kind, label in UNIT_FIELDS:
        values = row.get(field, [])
        if not isinstance(values, list):
            values = [values]
        parts.extend(f"{kind} [{label}]: {_compact(value, 300)}" for value in values if value)
    return "passage: " + "\n".join(parts)[:6000]


def _session_units(row):
    import codex_memory
    seen = set()
    units = []
    for field, kind, evidence_level in UNIT_FIELDS:
        values = row.get(field, [])
        if not isinstance(values, list):
            values = [values]
        for value in values:
            text = _compact(value)
            if not text or (kind, text) in seen:
                continue
            seen.add((kind, text))
            identity = json.dumps([row["session_id"], kind, text], ensure_ascii=False)
            units.append({"unit_id": hashlib.sha256(identity.encode()).hexdigest(),
                "unit_kind": kind, "text": text, "evidence_level": evidence_level,
                "source_type": "session", "source_session_id": row["session_id"],
                "source_path": codex_memory.card_relpath(row) + ".md",
                "project": row.get("project", ""), "cwd": row.get("cwd", ""),
                "title": row.get("title", ""), "updated_at": row.get("updated", ""),
                "task_family": row.get("task_family", "")})
            if len(units) >= MAX_UNITS_PER_SESSION:
                return units
    if not units and row.get("title"):
        text = _compact(row["title"])
        units.append({"unit_id": hashlib.sha256((row["session_id"] + text).encode()).hexdigest(),
            "unit_kind": "session_context", "text": text, "evidence_level": "context_only",
            "source_type": "session", "source_session_id": row["session_id"],
            "source_path": codex_memory.card_relpath(row) + ".md",
            "project": row.get("project", ""), "cwd": row.get("cwd", ""),
            "title": row["title"], "task_family": row.get("task_family", "")})
    return units


def _validated_experience_refs(refs):
    """Recheck provenance without mistaking a matching quote for task success."""
    if not isinstance(refs, list) or not refs:
        raise ValueError("Experience has no source quotations")
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"].strip():
            raise ValueError("Experience source path is missing")
        quote = ref.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("Experience source quotation is missing")
        path = Path(ref["path"]).expanduser().resolve()
        if not path.is_file() or quote not in path.read_text(encoding="utf-8"):
            raise ValueError("Experience source or quotation no longer exists: " + str(path))
    return refs


def _active_experience_units(memory_home, evidence_warnings=None):
    try:
        import codex_experience
    except ModuleNotFoundError as exc:
        if exc.name == "codex_experience":
            return []
        raise
    units = []
    for item in codex_experience.load_experiences(memory_home):
        if item.get("status") != "active" or not item.get("memory_id"):
            continue
        try:
            refs = _validated_experience_refs(item.get("evidence_refs"))
        except (ValueError, OSError) as exc:
            if evidence_warnings is not None:
                evidence_warnings.append({"memory_id": item["memory_id"],
                    "revision": item.get("revision"), "reason": str(exc)[:300]})
            continue
        action = _compact(item.get("recommended_action", ""), 320)
        if not action:
            continue
        # A published experience retains its own evidence level. Active does not
        # silently promote a candidate or an assistant claim to verified fact.
        text = (action + "\nConditions: " + _compact(item.get("conditions", ""), 160)
                + "\nAvoid: " + _compact(item.get("avoid", ""), 120))
        memory_id, revision = str(item["memory_id"]), item.get("revision", 0)
        units.append({"unit_id": f"experience:{memory_id}@{revision}",
            "unit_kind": "experience", "text": text, "source_type": "experience",
            "source_session_id": "", "source_path": ".index/experiences.sqlite3",
            "memory_id": memory_id, "revision": revision,
            "scope": item.get("scope"), "task_family": item.get("task_family", ""),
            "project": item.get("scope") if isinstance(item.get("scope"), str) else "",
            "title": action[:140], "evidence_refs": refs,
            "evidence_level": item.get("evidence_level", "unknown"),
            "updated_at": item.get("updated_at", "")})
    return units


def retrieval_units(memory_home, evidence_warnings=None):
    """Read-only unit construction. Never edits summaries or promotes evidence."""
    import codex_memory
    rows = list(codex_memory.retained_summaries(Path(memory_home)).values())
    return [unit for row in rows for unit in _session_units(row)] + _active_experience_units(Path(memory_home), evidence_warnings)


class Encoder:
    def __init__(self, model_dir):
        import onnxruntime as ort
        from transformers import AutoTokenizer
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(model_dir / "onnx/model_quantized.onnx"),
            sess_options=options, providers=["CPUExecutionProvider"])
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True,
                                                       trust_remote_code=False)
        self.names = {x.name for x in self.session.get_inputs()}

    def encode(self, texts):
        import numpy as np
        batches = []
        for start in range(0, len(texts), 8):
            tokens = self.tokenizer(texts[start:start+8], padding=True, truncation=True,
                                    max_length=512, return_tensors="np")
            if "token_type_ids" in self.names and "token_type_ids" not in tokens:
                tokens["token_type_ids"] = np.zeros_like(tokens["input_ids"])
            output = self.session.run(None, {k:v for k,v in tokens.items() if k in self.names})[0]
            mask = tokens["attention_mask"][..., None]
            vectors = (output * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
            vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
            batches.append(vectors.astype("float32"))
        return np.concatenate(batches) if batches else np.zeros((0, 384), dtype="float32")


def model_fingerprint(provenance):
    value = {"schema": INDEX_SCHEMA_VERSION, "policy": EMBEDDING_POLICY, "model": provenance}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _cache(path, fingerprint):
    import numpy as np
    if not path.exists():
        return {}
    try:
        with np.load(path, allow_pickle=False) as old:
            if int(old["index_schema"]) != INDEX_SCHEMA_VERSION or str(old["model_fingerprint"]) != fingerprint:
                return {}
            hashes, vectors = old["hashes"].tolist(), old["vectors"]
            if vectors.ndim != 2 or not vectors.shape[1] or len(hashes) != len(vectors) or not np.isfinite(vectors).all():
                return {}
            return dict(zip(hashes, vectors))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return {}


def build(memory_home, encoder=None):
    import numpy as np
    import codex_memory
    memory_home = Path(memory_home)
    rows = list(codex_memory.retained_summaries(memory_home).values())
    evidence_warnings = []
    units = [unit for row in rows for unit in _session_units(row)] + _active_experience_units(memory_home, evidence_warnings)
    model_dir = memory_home / "models/multilingual-e5-small"
    provenance = json.loads((model_dir / "model-provenance.json").read_text())
    fingerprint = model_fingerprint(provenance)
    texts = [document(unit) for unit in units]
    hashes = [hashlib.sha256((fingerprint + text).encode()).hexdigest() for text in texts]
    path = memory_home / ".index/semantic.npz"
    cached = _cache(path, fingerprint)
    missing = list(dict.fromkeys(key for key in hashes if key not in cached))
    if missing:
        encoder = encoder or Encoder(model_dir)
        by_hash = dict(zip(hashes, texts))
        encoded = np.asarray(encoder.encode([by_hash[key] for key in missing]), dtype="float32")
        if encoded.ndim != 2 or not encoded.shape[1] or len(encoded) != len(missing) or not np.isfinite(encoded).all():
            raise ValueError("Invalid offline encoder output; index not replaced")
        cached.update(zip(missing, encoded))
    vectors = np.stack([cached[key] for key in hashes]) if hashes else np.zeros((0, 384), dtype="float32")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    with tmp.open("wb") as stream:
        np.savez_compressed(stream, hashes=np.asarray(hashes), vectors=vectors,
            units=np.asarray([json.dumps(unit, ensure_ascii=False) for unit in units]),
            sessions=np.asarray([json.dumps(row, ensure_ascii=False) for row in rows]),
            index_schema=np.asarray(INDEX_SCHEMA_VERSION), model_fingerprint=np.asarray(fingerprint),
            model_id=np.asarray(provenance.get("revision", "unknown")))
    tmp.chmod(0o600)
    tmp.replace(path)
    health = {"status": "ok", "checked_at": datetime.now(timezone.utc).isoformat(),
              "documents": len(rows), "units": len(units), "encoded": len(missing),
              "experiences": sum(unit["source_type"] == "experience" for unit in units),
              "evidence_warnings": evidence_warnings,
              "index_schema": INDEX_SCHEMA_VERSION, "model_fingerprint": fingerprint,
              "model_revision": provenance.get("revision", "unknown")}
    hp = memory_home / ".index/semantic-health.json"
    temp = hp.with_suffix(f".tmp.{os.getpid()}")
    temp.write_text(json.dumps(health), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(hp)
    return health


def _matches_project(value, project):
    if not isinstance(value, str) or not value.strip() or not project:
        return False
    value, project = value.rstrip("/"), str(project).rstrip("/")
    # Two explicit paths must match as paths, not just coincident basenames.
    if "/" in value and "/" in project:
        return value == project
    return value == project or Path(value).name == Path(project).name


def _in_scope(unit, project=None, family=None):
    if family and unit.get("task_family") != family:
        return False
    if unit["source_type"] != "experience":
        if project and "/" in str(project) and "/" in unit.get("cwd", ""):
            return _matches_project(unit["cwd"], project)
        return not project or _matches_project(unit.get("cwd", ""), project) or _matches_project(unit.get("project", ""), project)
    scope = unit.get("scope")
    if scope == "global":
        return True
    if isinstance(scope, dict):
        scope = scope.get("project") if scope.get("type") != "global" else "global"
        if scope == "global":
            return True
    # Family similarity never authorizes crossing a project's experience scope.
    return bool(project and _matches_project(scope, project))


def _terms(query):
    terms = set(re.findall(r"[a-z0-9_-]{2,}", query.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", query):
        terms.update(run[i:i+2] for i in range(len(run)-1))
    return terms


def _experience_session(unit):
    return {"session_id": "experience:" + unit["memory_id"], "title": unit["title"],
            "project": unit.get("project", ""), "date": unit.get("updated_at", "")[:10],
            "status": "active", "source": "experience", "evidence_refs": unit.get("evidence_refs", [])}


def search(memory_home, query, limit=5, project=None, family=None,
           min_similarity=DEFAULT_MIN_SIMILARITY, max_per_session=2):
    """Return bounded, labelled candidates. A similarity score is not confidence.

    Scope is enforced before ranking. Thresholds are operator-tunable heuristics;
    use measured task sets to calibrate them rather than claiming universal quality.
    """
    import numpy as np
    if not query.strip() or limit <= 0:
        return []
    if not -1 <= min_similarity <= 1 or max_per_session < 1:
        raise ValueError("Invalid similarity threshold or per-session result budget")
    memory_home = Path(memory_home)
    path = memory_home / ".index/semantic.npz"
    build(memory_home)
    encoder = Encoder(memory_home / "models/multilingual-e5-small")
    query_vector = encoder.encode(["query: " + query[:1000]])[0]
    with np.load(path, allow_pickle=False) as index:
        scores = index["vectors"] @ query_vector
        units = [json.loads(str(unit)) for unit in index["units"]]
        sessions = {row["session_id"]: row for row in (json.loads(str(row)) for row in index["sessions"])}
    terms = _terms(query)
    ranked = []
    for i, unit in enumerate(units):
        similarity = float(scores[i])
        if not _in_scope(unit, project, family) or not np.isfinite(similarity) or similarity < min_similarity:
            continue
        text = (unit["text"] + " " + unit.get("title", "") + " " + unit.get("project", "")).lower()
        lexical = sum(term in text for term in terms) / max(len(terms), 1)
        score = similarity + 0.08 * lexical + KIND_PRIORITY.get(unit["unit_kind"], 0)
        ranked.append((score, similarity, unit))
    ranked.sort(key=lambda item: (-item[0], item[2]["unit_id"]))
    results, seen, source_counts = [], set(), {}
    for score, similarity, unit in ranked:
        source_id = unit.get("source_session_id") or "experience:" + unit["memory_id"]
        key = (source_id, re.sub(r"\s+", " ", unit["text"]).strip())
        if key in seen or source_counts.get(source_id, 0) >= max_per_session:
            continue
        seen.add(key)
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        session = sessions[unit["source_session_id"]] if unit["source_type"] == "session" else _experience_session(unit)
        results.append({"score": score, "similarity": similarity, "session": session,
                        "unit": unit, "source_type": unit["source_type"],
                        "source_path": unit["source_path"], "evidence_level": unit["evidence_level"]})
        if len(results) >= min(limit, MAX_SEARCH_RESULTS):
            break
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "search"])
    parser.add_argument("query", nargs="?")
    parser.add_argument("--memory-home", type=Path, default=Path(os.environ.get("CODEX_MEMORY_HOME", str(Path.home()/"CodexMemory"))))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--project")
    parser.add_argument("--family")
    parser.add_argument("--min-similarity", type=float, default=DEFAULT_MIN_SIMILARITY)
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build(args.memory_home)))
    else:
        if not args.query:
            parser.error("search requires a query")
        results = search(args.memory_home, args.query, args.limit, args.project, args.family, args.min_similarity)
        for item in results:
            unit, session = item["unit"], item["session"]
            print(f"{item['score']:.4f} [{unit['unit_kind']}; {item['evidence_level']}] {_compact(session['title'], 100)} · {_compact(session.get('project', ''), 80)}")
            print(_compact(unit["text"], 280))
            print(args.memory_home / item["source_path"])
            if unit["source_type"] == "experience":
                print(f"Memory: {unit['memory_id']} r{unit['revision']}")
                for ref in unit.get("evidence_refs", [])[:2]:
                    print(str(ref["path"]) + " :: " + _compact(ref["quote"], 140))
        if not results:
            print("No candidate passed the scope and similarity filters; try keyword recall or a different query.")
