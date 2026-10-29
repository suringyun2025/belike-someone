from __future__ import annotations

import io
import mimetypes
import os
import zipfile
from pathlib import Path
from typing import Iterable

from .config import settings
from .security import sha256_bytes

TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".log",
    ".rst",
    ".json",
    ".jsonl",
    ".csv",
    ".html",
    ".htm",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
}
DOC_EXTENSIONS = {".pdf", ".docx", ".xlsx"}
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".sql",
    ".sh",
    ".ps1",
    ".vue",
    ".svelte",
}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}


def detect_source_type(filename: str, mime: str = "") -> str:
    ext = Path(filename).suffix.lower()
    if ext in AUDIO_EXTENSIONS or ext in VIDEO_EXTENSIONS or mime.startswith(("audio/", "video/")):
        return "media"
    if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in {".jsonl"} or "chat" in filename.lower() or "微信" in filename or "slack" in filename.lower():
        return "chat"
    return "document"


def guess_mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def save_source_file(project_id: str, filename: str, data: bytes) -> tuple[str, str, int]:
    digest = sha256_bytes(data)
    ext = Path(filename).suffix.lower()
    target = settings.sources_dir / project_id / f"{digest}{ext}"
    if not target.exists():
        atomic_write(target, data)
    return digest, str(target), len(data)


def save_artifact(name: str, data: bytes, suffix: str = "") -> tuple[str, str]:
    digest = sha256_bytes(data)
    target = settings.artifacts_dir / digest[:2] / f"{digest}{suffix}"
    if not target.exists():
        atomic_write(target, data)
    return digest, str(target)


def read_text_file(path: str | Path, max_bytes: int = 8_000_000) -> str:
    raw = Path(path).read_bytes()[:max_bytes]
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def safe_extract_zip(data: bytes, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos: Iterable[zipfile.ZipInfo] = archive.infolist()
        entries = list(infos)
        if len(entries) > settings.max_zip_entries:
            raise ValueError(f"ZIP 文件条目超过限制（{settings.max_zip_entries}）")
        for info in entries:
            total += info.file_size
            if total > settings.max_zip_uncompressed_mb * 1024 * 1024:
                raise ValueError("ZIP 解压后体积超过限制")
            name = info.filename.replace("\\", "/")
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts or ":" in name:
                raise ValueError(f"ZIP 包含不安全路径：{info.filename}")
            if info.is_dir():
                continue
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            extracted.append(target)
    return extracted


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
