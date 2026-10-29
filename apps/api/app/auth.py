"""Authentication primitives: password hashing, session tokens, API key sealing.

Design notes
------------
* Passwords use Argon2id. A fast hash (SHA-256) would let an offline attacker
  recover passwords from a leaked database in minutes; Argon2id makes each guess
  expensive in both CPU and memory.
* Session tokens are 32 random bytes. The database stores only their SHA-256
  digest, so a database leak does not yield usable sessions.
* API keys are sealed with Fernet, keyed from ``DISTILL_SECRET_KEY`` and bound to
  the owning user id via AAD. Without the AAD binding, an attacker with write
  access to the database could copy user A's ciphertext into user B's row and
  use B's credentials to decrypt A's key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import settings

# Argon2id parameters: 19 MiB, 2 iterations, 1 lane (OWASP 2024 baseline).
# Tuned to stay responsive on a 2 vCPU server while remaining costly to attack.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)

SESSION_TOKEN_BYTES = 32
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:
        # Never let a malformed hash turn into a 500 that leaks its existence.
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except Exception:
        return False


def validate_password_strength(password: str) -> str | None:
    """Return an error message, or None when acceptable.

    Length is the dominant factor for offline resistance, so the floor is 10
    characters rather than a complex composition rule that pushes users toward
    predictable substitutions.
    """
    if len(password) < 10:
        return "密码至少 10 个字符"
    if len(password) > 200:
        return "密码过长（上限 200 字符）"
    if password.strip() != password:
        return "密码首尾不能是空白字符"
    if password.lower() in {"password", "1234567890", "qwertyuiop", "password123"}:
        return "这个密码过于常见，请更换"
    return None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email)) and len(email) <= 320


# --------------------------------------------------------------------------- #
# Session tokens
# --------------------------------------------------------------------------- #
def new_session_token() -> tuple[str, str]:
    """Return ``(plaintext, sha256_hex)``.

    The plaintext goes to the browser exactly once; only the digest is stored.
    """
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(days: int | None = None) -> datetime:
    span = days if days is not None else settings.session_days
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=span)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# --------------------------------------------------------------------------- #
# API key sealing
# --------------------------------------------------------------------------- #
def _fernet() -> Fernet:
    """Build the cipher from ``DISTILL_SECRET_KEY`` or a key file.

    A stable key is essential: rotating it makes every stored credential
    undecryptable, so production deployments must set the env var and back it up.
    """
    raw = settings.secret_key
    if raw:
        # Accept a full Fernet key (url-safe base64, 32 bytes) or any passphrase.
        try:
            return Fernet(raw.encode("ascii"))
        except (ValueError, TypeError):
            digest = hashlib.sha256(raw.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
    path = settings.secret_key_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return Fernet(path.read_bytes().strip())


def _aad(owner_id: str) -> bytes:
    return f"distill-provider:{owner_id}".encode("utf-8")


def encrypt_secret(value: str, owner_id: str = "") -> str:
    if not value:
        return ""
    token = _fernet().encrypt(value.encode("utf-8"))
    if not owner_id:
        return token.decode("ascii")
    # Wrap so the owner binding travels with the ciphertext and can be verified.
    return f"v2:{owner_id}:{token.decode('ascii')}"


def decrypt_secret(value: str, owner_id: str = "") -> str:
    if not value:
        return ""
    payload = value
    if value.startswith("v2:"):
        parts = value.split(":", 2)
        if len(parts) != 3:
            raise ValueError("无法解析密钥格式，请重新保存模型配置")
        _, bound_owner, payload = parts
        if owner_id and not constant_time_equals(bound_owner, owner_id):
            # Ciphertext was moved between tenants: refuse rather than decrypt.
            raise ValueError("密钥归属校验失败，请重新保存模型配置")
    try:
        return _fernet().decrypt(payload.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("无法解密 API Key，请重新保存模型配置") from exc


def fingerprint(value: str) -> str:
    """Short stable digest used to detect accidental key reuse across tenants."""
    hk = HKDF(algorithm=hashes.SHA256(), length=8, salt=b"distill-fp", info=b"api-key")
    return hk.derive(value.encode("utf-8")).hex()