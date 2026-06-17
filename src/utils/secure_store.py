"""Fernet based helpers for local sensitive data.

The app stores runtime data on the user's machine.  API keys and cookies still
need at-rest encryption so accidental file sharing does not expose sessions.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


PASSPHRASE_ENV = "XHS_KEY_PASSPHRASE"
PASSPHRASE_FILE = Path.home() / ".xhs_key_passphrase"


class SecureStoreError(RuntimeError):
    """Raised when encrypted local data cannot be read or written."""


def _lock_down(path: Path) -> None:
    try:
        os.chmod(str(path), 0o600)
    except (OSError, AttributeError):
        logger.debug("chmod 操作不支持或失败: %s", path)


def get_or_create_passphrase() -> str:
    env_passphrase = os.environ.get(PASSPHRASE_ENV)
    if env_passphrase:
        return env_passphrase

    if PASSPHRASE_FILE.exists():
        try:
            value = PASSPHRASE_FILE.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError as exc:
            raise SecureStoreError(f"Cannot read encryption passphrase: {exc}") from exc

    value = secrets.token_urlsafe(32)
    try:
        PASSPHRASE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PASSPHRASE_FILE.write_text(value, encoding="utf-8")
        _lock_down(PASSPHRASE_FILE)
    except OSError as exc:
        raise SecureStoreError(f"Cannot create encryption passphrase: {exc}") from exc
    return value


def get_fernet(passphrase: str | None = None) -> Fernet:
    key = Fernet.generate_key()
    if passphrase is None:
        passphrase = get_or_create_passphrase()
    import base64
    import hashlib

    key = base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_text(text: str, passphrase: str | None = None) -> str:
    return get_fernet(passphrase).encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_text(token: str | bytes, passphrase: str | None = None) -> str:
    raw = token.encode("ascii") if isinstance(token, str) else token
    try:
        return get_fernet(passphrase).decrypt(raw).decode("utf-8")
    except InvalidToken as exc:
        raise SecureStoreError("Encrypted data cannot be decrypted with the current key") from exc


def atomic_write_text(path: str | Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _lock_down(tmp_path)
        os.replace(tmp_path, path)
        _lock_down(path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                logger.debug("临时文件清理失败: %s", tmp_path)


def save_json(path: str | Path, data: Any, passphrase: str | None = None) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    atomic_write_text(path, encrypt_text(payload, passphrase))


def load_json(
    path: str | Path,
    *,
    passphrase: str | None = None,
    allow_plaintext_migration: bool = False,
) -> Any:
    path = Path(path)
    raw = path.read_bytes()
    try:
        payload = decrypt_text(raw, passphrase)
    except SecureStoreError:
        if not allow_plaintext_migration:
            raise
        payload = raw.decode("utf-8")
        data = json.loads(payload)
        save_json(path, data, passphrase)
        return data
    return json.loads(payload)

import logging
logger = logging.getLogger(__name__)
