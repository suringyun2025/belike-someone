"""Download a CTranslate2 faster-whisper model from ModelScope.

HuggingFace may be unreachable; ModelScope mirrors Systran/faster-whisper-base.
The app auto-detects data/models/faster-whisper-base.

Usage:
  uv run --project apps/api python scripts/fetch_whisper_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

REPO = "Systran/faster-whisper-base"
BASE = f"https://modelscope.cn/models/{REPO}/resolve/master"
FILES = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]
ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "models" / "faster-whisper-base"


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = TARGET / name
        if target.exists() and target.stat().st_size > 0:
            print(f"exists {name} ({target.stat().st_size} bytes)")
            continue
        print(f"download {BASE}/{name}")
        try:
            response = requests.get(f"{BASE}/{name}", stream=True, timeout=180)
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
    print(f"model path: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
