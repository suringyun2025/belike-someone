from __future__ import annotations

import hashlib
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CN_MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_CN_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
_API_KEY_RE = re.compile(r"(?:sk|rk|pk)-[A-Za-z0-9_\-]{16,}")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{10,}")
_IP_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")

REDACTIONS = [
    ("EMAIL", _EMAIL_RE),
    ("PHONE", _CN_MOBILE_RE),
    ("ID_CARD", _CN_ID_RE),
    ("BANK_CARD", _BANK_CARD_RE),
    ("API_KEY", _API_KEY_RE),
    ("BEARER_TOKEN", _BEARER_RE),
    ("IP_ADDRESS", _IP_RE),
    ("PRIVATE_KEY", _PRIVATE_KEY_RE),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def _fernet() -> Fernet:
    path: Path = settings.secret_key_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return Fernet(path.read_bytes().strip())


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("无法解密 API Key，请重新保存模型配置") from exc


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "已配置 · " + ("*" * 8) + value[-4:]


def redact_text(text: str) -> tuple[str, int]:
    count = 0
    for label, pattern in REDACTIONS:
        text, n = pattern.subn(f"[REDACTED:{label}]", text)
        count += n
    return text, count


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for _, pattern in REDACTIONS)
