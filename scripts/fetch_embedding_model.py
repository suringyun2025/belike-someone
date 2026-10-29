"""Download the BGE small Chinese ONNX embedding model from ModelScope.

HuggingFace is often unreachable from mainland China. The fastembed cache is
populated in a HuggingFace-compatible layout and auto-discovered by the app.

Usage:
  uv run --project apps/api python scripts/fetch_embedding_model.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import requests

REPO = "Qdrant/bge-small-zh-v1.5"
BASE = f"https://modelscope.cn/models/{REPO}/resolve/master"
FILES = [
    "model_optimized.onnx",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
]
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "models" / "models--Qdrant--bge-small-zh-v1.5"


def main() -> int:
    revision = hashlib.sha1(REPO.encode("utf-8")).hexdigest()
    snapshot = CACHE / "snapshots" / revision
    snapshot.mkdir(parents=True, exist_ok=True)
    (CACHE / "refs").mkdir(parents=True, exist_ok=True)
    (CACHE / "refs" / "main").write_text(revision, encoding="utf-8")
    for name in FILES:
        target = snapshot / name
        if target.exists() and target.stat().st_size > 0:
            print(f"exists {name} ({target.stat().st_size} bytes)")
            continue
        url = f"{BASE}/{name}"
        print(f"download {url}")
        try:
            response = requests.get(url, stream=True, timeout=120)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"failed {name}: {exc}", file=sys.stderr)
            return 1
        tmp = target.with_suffix(target.suffix + ".part")
        with open(tmp, "wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
        tmp.replace(target)
        print(f"saved {name} ({target.stat().st_size} bytes)")
    print(f"model path: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
