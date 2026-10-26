#!/usr/bin/env python3
"""Offline multilingual E5 retrieval. All text and embeddings stay on this host."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def document(row):
    parts = [row.get("title", ""), row.get("project", "")]
    for key in ("goal", "decisions", "claims", "open_items"):
        values = row.get(key, [])
        if not isinstance(values, list):
            values = [values]
        parts += [str(value)[:240] for value in values[:2]]
    def flatten(value):
        return "\n".join(flatten(x) for x in value) if isinstance(value, list) else str(value)
    return "passage: " + "\n".join(flatten(x) for x in parts)[:6000]


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


def build(memory_home, encoder=None):
    import numpy as np
    import codex_memory
    rows = list(codex_memory.retained_summaries(memory_home).values())
    model_dir = memory_home / "models/multilingual-e5-small"
    provenance = json.loads((model_dir / "model-provenance.json").read_text())
    model_id = provenance["revision"]
    texts = [document(row) for row in rows]
    hashes = [hashlib.sha256((model_id + text).encode()).hexdigest() for text in texts]
    path = memory_home / ".index/semantic.npz"
    cached = {}
    if path.exists():
        with np.load(path, allow_pickle=False) as old:
            cached = {key: value for key,value in zip(old["hashes"].tolist(), old["vectors"])}
    missing = [i for i,key in enumerate(hashes) if key not in cached]
    if missing:
        encoder = encoder or Encoder(model_dir)
        for i,vector in zip(missing, encoder.encode([texts[i] for i in missing])):
            cached[hashes[i]] = vector
    vectors = np.stack([cached[key] for key in hashes]) if hashes else np.zeros((0,384),dtype="float32")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    with tmp.open("wb") as stream:
        np.savez_compressed(stream, hashes=np.asarray(hashes), vectors=vectors,
            rows=np.asarray([json.dumps(row, ensure_ascii=False) for row in rows]),
            model_id=np.asarray(model_id))
    tmp.chmod(0o600)
    tmp.replace(path)
    health = {"status": "ok", "checked_at": datetime.now(timezone.utc).isoformat(),
              "documents": len(rows), "encoded": len(missing), "model_revision": model_id}
    hp = memory_home / ".index/semantic-health.json"
    temp = hp.with_suffix(f".tmp.{os.getpid()}")
    temp.write_text(json.dumps(health), encoding="utf-8")
    temp.replace(hp)
    return health


def search(memory_home, query, limit=5):
    import numpy as np
    path = memory_home / ".index/semantic.npz"
    build(memory_home)
    encoder = Encoder(memory_home / "models/multilingual-e5-small")
    query_vector = encoder.encode(["query: " + query])[0]
    with np.load(path, allow_pickle=False) as index:
        scores = index["vectors"] @ query_vector
        rows = [json.loads(str(row)) for row in index["rows"]]
        # Hybrid reranking retains semantic paraphrase matches while boosting
        # precise project terms, including unsegmented Chinese bigrams.
        terms = set(re.findall(r"[a-z0-9_-]{2,}", query.lower()))
        for run in re.findall(r"[\u4e00-\u9fff]+", query):
            terms.update(run[i:i+2] for i in range(len(run)-1))
        for i, row in enumerate(rows):
            text = document(row).lower()
            scores[i] += 0.08 * sum(term in text for term in terms) / max(len(terms), 1)
        selected = np.argsort(-scores)[:limit]
        return [{"score": float(scores[i]), "session": rows[i]} for i in selected]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "search"])
    parser.add_argument("query", nargs="?")
    parser.add_argument("--memory-home", type=Path, default=Path(os.environ.get("CODEX_MEMORY_HOME", str(Path.home()/"CodexMemory"))))
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build(args.memory_home)))
    else:
        if not args.query:
            parser.error("search requires a query")
        for item in search(args.memory_home, args.query, args.limit):
            s = item["session"]
            print(f"{item['score']:.4f} {s['title']} · {s['project']}")
            print(args.memory_home / "sessions" / s["date"] / s["session_id"] / "memory.md")
