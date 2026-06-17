"""
API Key 管理器
支持多 LLM 提供商、加密存储、轮询使用
"""

import json
import os
import base64
import hashlib
import time
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from enum import Enum
from src.utils.secure_store import get_or_create_passphrase

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet
    _HAS_FERNET = True
except ImportError as exc:
    raise RuntimeError(
        "cryptography is required for API key encryption. "
        "Install dependencies with: pip install -r requirements.txt"
    ) from exc


class Provider(str, Enum):
    OPENAI = "openai"
    KIMI = "kimi"
    QWEN = "qwen"  # 通义千问


# 提供商默认配置（配置驱动，不硬编码在 Provider 枚举里）
PROVIDER_CONFIG = {
    Provider.OPENAI: {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "max_tokens": 2000,
    },
    Provider.KIMI: {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "max_tokens": 2000,
    },
    Provider.QWEN: {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "max_tokens": 2000,
    },
}


@dataclass
class APIKeyEntry:
    """单个 API Key 条目"""
    provider: Provider
    api_key: str
    base_url: Optional[str] = None
    model: Optional[str] = None
    max_tokens: int = 2000
    enabled: bool = True
    last_used: float = 0.0
    error_count: int = 0
    max_errors: int = 3


# ----------------------------------------------------------
# 加密工具（Fernet 优先，XOR 降级）
# ----------------------------------------------------------

_PASSPHRASE_FILE = ".xhs_key_passphrase"


def _get_or_create_passphrase() -> str:
    """
    获取加密密码：优先环境变量 > 配置文件 > 自动生成并持久化。
    不再使用任何硬编码默认密码。
    """
    return get_or_create_passphrase()


def _derive_key(passphrase: str) -> bytes:
    """从密码派生加密密钥"""
    return hashlib.sha256(passphrase.encode()).digest()


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    """简单 XOR 加密（降级方案，仅在 cryptography 不可用时使用）"""
    key_repeated = (key * (len(data) // len(key) + 1))[: len(data)]
    return bytes(a ^ b for a, b in zip(data, key_repeated))


def _fernet_encrypt(plaintext: str, passphrase: str) -> str:
    """使用 Fernet 加密，返回 base64"""
    key = base64.urlsafe_b64encode(_derive_key(passphrase))
    f = Fernet(key)
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def _fernet_decrypt(ciphertext_b64: str | bytes, passphrase: str) -> str:
    """解密 Fernet 密文"""
    key = base64.urlsafe_b64encode(_derive_key(passphrase))
    f = Fernet(key)
    token = ciphertext_b64 if isinstance(ciphertext_b64, bytes) else ciphertext_b64.encode("ascii")
    return f.decrypt(token).decode("utf-8")


def _xor_encrypt_text(text: str, passphrase: str) -> str:
    """XOR 加密文本并返回 base64（降级方案）"""
    key = _derive_key(passphrase)
    encrypted = _xor_encrypt(text.encode("utf-8"), key)
    return base64.b64encode(encrypted).decode("ascii")


def _xor_decrypt_text(encrypted_b64: str, passphrase: str) -> str:
    """解密 XOR base64 密文"""
    key = _derive_key(passphrase)
    encrypted = base64.b64decode(encrypted_b64)
    decrypted = _xor_encrypt(encrypted, key)
    return decrypted.decode("utf-8")


_FERNET_PREFIX = "gAAAAA"
_FERNET_PREFIX_BYTES = _FERNET_PREFIX.encode("ascii")

# Migration only: when users explicitly provide an old XOR passphrase.
# New saves always use the per-machine passphrase from secure_store + Fernet.
_LEGACY_XOR_PASSPHRASES = tuple(
    passphrase
    for passphrase in (os.environ.get("XHS_LEGACY_KEY_PASSPHRASE"),)
    if passphrase
)


def _encrypt_text(text: str, passphrase: str) -> str:
    """加密文本，优先使用 Fernet"""
    if _HAS_FERNET:
        return _fernet_encrypt(text, passphrase)
    return _xor_encrypt_text(text, passphrase)


def _decrypt_raw_xor(raw: bytes, passphrase: str) -> str:
    key = _derive_key(passphrase)
    decrypted = _xor_encrypt(raw, key)
    return decrypted.decode("utf-8")


def _decrypt_text(ciphertext_b64: str | bytes, passphrase: str) -> str:
    """
    解密文本。自动检测格式：
    - 以 gAAAAA 开头 → Fernet
    - 否则 → XOR（兼容旧版 keys.enc）
    """
    raw = ciphertext_b64.strip() if isinstance(ciphertext_b64, bytes) else ciphertext_b64.strip().encode("utf-8")
    if raw.startswith(_FERNET_PREFIX_BYTES) and _HAS_FERNET:
        return _fernet_decrypt(raw, passphrase)

    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return _decrypt_raw_xor(raw, passphrase)

    return _xor_decrypt_text(text, passphrase)


def _decrypt_text_with_legacy(ciphertext_b64: str | bytes, passphrase: str) -> tuple[str, bool]:
    """Decrypt current data, falling back to one-time legacy XOR migration."""
    errors = []
    candidates = [(passphrase, False)]
    candidates.extend((legacy, True) for legacy in _LEGACY_XOR_PASSPHRASES if legacy != passphrase)

    for candidate, legacy in candidates:
        try:
            return _decrypt_text(ciphertext_b64, candidate), legacy
        except Exception as exc:
            errors.append(exc)

    if errors:
        raise errors[-1]
    raise ValueError("No passphrase candidates available")


def _mask_key(api_key: str) -> str:
    """统一脱敏：前4 + **** + 后4"""
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]


class APIKeyManager:
    """
    API Key 管理器

    特性：
    - 支持 OpenAI / Kimi / 通义千问
    - Fernet 加密存储到本地文件（兼容旧 XOR 格式）
    - Per-key 索引轮询
    - 失败自动禁用（超过阈值）
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        passphrase: Optional[str] = None,
    ):
        self._keys: list[APIKeyEntry] = []
        # Per-key 轮询索引：{provider: index}
        self._round_robin: dict[str, int] = {}

        if storage_path:
            self._storage_path = Path(storage_path)
        else:
            self._storage_path = Path.home() / ".xhs-publisher" / "keys.enc"

        self._passphrase = passphrase or _get_or_create_passphrase()
        self._load()

    # ----------------------------------------------------------
    # 公开 API
    # ----------------------------------------------------------

    def add_key(
        self,
        provider: str | Provider,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> bool:
        """
        添加一个 API Key。如果相同 provider + api_key 已存在，跳过并返回 False。
        """
        provider = Provider(provider) if isinstance(provider, str) else provider

        # 检查重复
        for existing in self._keys:
            if existing.provider == provider and existing.api_key == api_key:
                logger.debug("API key already exists for %s, skipping", provider.value)
                return False

        config = PROVIDER_CONFIG.get(provider, {})
        entry = APIKeyEntry(
            provider=provider,
            api_key=api_key,
            base_url=base_url or config.get("base_url"),
            model=model or config.get("model"),
            max_tokens=max_tokens or config.get("max_tokens", 2000),
        )
        self._keys.append(entry)
        self._save()
        return True

    def remove_key(self, api_key: str) -> bool:
        """移除指定的 API Key"""
        before = len(self._keys)
        self._keys = [k for k in self._keys if k.api_key != api_key]
        if len(self._keys) < before:
            self._save()
            return True
        return False

    def get_key(
        self,
        provider: Optional[str | Provider] = None,
    ) -> Optional[APIKeyEntry]:
        """
        Per-key 索引轮询获取一个可用的 API Key。

        Args:
            provider: 指定提供商，None 则不限
        """
        if not self._keys:
            return None

        if provider:
            provider = Provider(provider) if isinstance(provider, str) else provider
            candidates = [
                k for k in self._keys
                if k.provider == provider and k.enabled and k.error_count < k.max_errors
            ]
        else:
            candidates = [
                k for k in self._keys
                if k.enabled and k.error_count < k.max_errors
            ]

        if not candidates:
            return None

        # Per-key 轮询：使用 provider 作为 key 的索引
        provider_key = provider.value if provider else "__all__"
        idx = self._round_robin.get(provider_key, 0) % len(candidates)
        self._round_robin[provider_key] = idx + 1
        entry = candidates[idx]
        entry.last_used = time.time()
        return entry

    def report_success(self, api_key: str) -> None:
        """报告调用成功，重置错误计数"""
        for k in self._keys:
            if k.api_key == api_key:
                k.error_count = 0
                break

    def report_error(self, api_key: str, permanent: bool = False) -> None:
        """
        报告调用失败，增加错误计数。

        Args:
            api_key: 失败的 key
            permanent: True 表示永久错误（如 key 无效），直接禁用
        """
        for k in self._keys:
            if k.api_key == api_key:
                if permanent:
                    k.enabled = False
                    k.error_count = k.max_errors
                    logger.warning("API key permanently disabled: %s...", _mask_key(api_key))
                else:
                    k.error_count += 1
                    if k.error_count >= k.max_errors:
                        k.enabled = False
                        logger.warning("API key disabled after %d errors: %s...",
                                       k.error_count, _mask_key(api_key))
                break

    def list_keys(self) -> list[dict]:
        """列出所有 key（脱敏）"""
        result = []
        for k in self._keys:
            result.append({
                "provider": k.provider.value,
                "key_masked": _mask_key(k.api_key),
                "model": k.model,
                "enabled": k.enabled,
                "error_count": k.error_count,
            })
        return result

    def has_keys(self, provider: Optional[str | Provider] = None) -> bool:
        """是否有可用的 key"""
        return self.get_key(provider) is not None

    # ----------------------------------------------------------
    # 环境变量批量加载
    # ----------------------------------------------------------

    def load_from_env(self) -> int:
        """
        从环境变量加载 API Key。

        支持的环境变量格式：
        - XHS_OPENAI_KEY / OPENAI_API_KEY
        - XHS_KIMI_KEY / KIMI_API_KEY
        - XHS_QWEN_KEY
        - XHS_OPENAI_BASE_URL / OPENAI_BASE_URL（可选）
        - XHS_OPENAI_MODEL / OPENAI_MODEL（可选）
        """
        count = 0
        env_map = [
            (Provider.OPENAI, "XHS_OPENAI_KEY", "OPENAI_API_KEY"),
            (Provider.KIMI, "XHS_KIMI_KEY", "KIMI_API_KEY"),
            (Provider.QWEN, "XHS_QWEN_KEY", "QWEN_API_KEY"),
        ]
        for provider, primary, fallback in env_map:
            key = os.environ.get(primary) or os.environ.get(fallback)
            if key:
                prefix = provider.value.upper()
                base_url = os.environ.get(f"XHS_{prefix}_BASE_URL") or os.environ.get(f"{prefix}_BASE_URL")
                model = os.environ.get(f"XHS_{prefix}_MODEL") or os.environ.get(f"{prefix}_MODEL")
                if self.add_key(provider, key, base_url=base_url, model=model):
                    count += 1
        return count

    # ----------------------------------------------------------
    # 持久化
    # ----------------------------------------------------------

    def _save(self) -> None:
        """加密保存到文件"""
        data = []
        for k in self._keys:
            data.append({
                "provider": k.provider.value,
                "api_key": k.api_key,
                "base_url": k.base_url,
                "model": k.model,
                "max_tokens": k.max_tokens,
                "enabled": k.enabled,
                "error_count": k.error_count,
            })
        json_str = json.dumps(data, ensure_ascii=False)
        encrypted = _encrypt_text(json_str, self._passphrase)

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(encrypted, encoding="utf-8")

    def _load(self) -> None:
        """从文件解密加载（自动兼容旧 XOR 格式和新 Fernet 格式）"""
        if not self._storage_path.exists():
            return
        try:
            encrypted = self._storage_path.read_bytes().strip()
            if not encrypted:
                return
            json_str, used_legacy = _decrypt_text_with_legacy(encrypted, self._passphrase)
            data = json.loads(json_str)
            self._keys = []
            for item in data:
                self._keys.append(APIKeyEntry(
                    provider=Provider(item["provider"]),
                    api_key=item["api_key"],
                    base_url=item.get("base_url"),
                    model=item.get("model"),
                    max_tokens=item.get("max_tokens", 2000),
                    enabled=item.get("enabled", True),
                    error_count=item.get("error_count", 0),
                ))
            logger.info("Loaded %d API keys from %s", len(self._keys), self._storage_path)
            if used_legacy:
                self._save()
                logger.info("Migrated legacy API key storage to Fernet: %s", self._storage_path)
        except Exception as e:
            logger.warning("Failed to load API keys from %s: %s (file may be corrupted or passphrase changed)",
                           self._storage_path, e)

    def reencrypt(self) -> bool:
        """
        将旧 XOR 格式的 keys.enc 重新加密为 Fernet 格式。
        Returns True if reencryption was performed.
        """
        if not _HAS_FERNET:
            logger.warning("cryptography not installed, cannot reencrypt to Fernet")
            return False
        if not self._storage_path.exists():
            return False

        raw = self._storage_path.read_bytes().strip()
        if raw.startswith(_FERNET_PREFIX_BYTES):
            return False

        try:
            json_str, _used_legacy = _decrypt_text_with_legacy(raw, self._passphrase)
            json.loads(json_str)
        except Exception as e:
            logger.error("Cannot reencrypt: failed to decrypt with current passphrase: %s", e)
            return False

        self._save()
        logger.info("Reencrypted keys.enc from XOR to Fernet format")
        return True


# ============================================================
# 便捷函数
# ============================================================

_global_manager: Optional[APIKeyManager] = None


def get_key_manager(
    storage_path: Optional[str] = None,
    passphrase: Optional[str] = None,
) -> APIKeyManager:
    """获取全局 APIKeyManager 单例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = APIKeyManager(storage_path, passphrase)
        _global_manager.load_from_env()
        _global_manager.reencrypt()
    return _global_manager
