#!/usr/bin/env bash
# Explicit opt-in: install a local CPU embedding runtime and pinned model data.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY_ROOT="${CODEX_MEMORY_HOME:-$HOME/CodexMemory}"
python3 -m venv "$MEMORY_ROOT/.runtime"
"$MEMORY_ROOT/.runtime/bin/python" -m pip install -r "$ROOT/requirements-semantic.txt"
"$MEMORY_ROOT/.runtime/bin/python" - "$MEMORY_ROOT" <<'PY'
from pathlib import Path
import json,sys
from huggingface_hub import snapshot_download
memory=Path(sys.argv[1]);root=memory/'models/multilingual-e5-small'
repo='Xenova/multilingual-e5-small';revision='761b726dd34fb83930e26aab4e9ac3899aa1fa78'
snapshot_download(repo_id=repo,revision=revision,local_dir=str(root),token=False,
    allow_patterns=['onnx/model_quantized.onnx','tokenizer.json','tokenizer_config.json',
                    'special_tokens_map.json','config.json','sentencepiece.bpe.model'])
(root/'model-provenance.json').write_text(json.dumps({'repo':repo,'revision':revision,'weights':'onnx/model_quantized.onnx'}))
PY
"$MEMORY_ROOT/.runtime/bin/python" "$MEMORY_ROOT/bin/codex_semantic.py" build --memory-home "$MEMORY_ROOT"
