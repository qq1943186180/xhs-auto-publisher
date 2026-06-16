"""
API Key 管理器
支持多 LLM 提供商、加密存储、轮询使用
"""

import json
import os
import base64
import hashlib
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Provider(str, Enum):
    OPENAI = "openai"
    KIMI = "kimi"
    QWEN = "qwen"  # 通义千问


# 提供商默认配置
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


def _derive_key(passphrase: str) -> bytes:
    """从密码派生加密密钥"""
    return hashlib.sha256(passphrase.encode()).digest()


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    """简单 XOR 加密（轻量级，非军事级安全）"""
    key_repeated = (key * (len(data) // len(key) + 1))[: len(data)]
    return bytes(a ^ b for a, b in zip(data, key_repeated))


def _encrypt_text(text: str, passphrase: str) -> str:
    """加密文本并返回 base64"""
    key = _derive_key(passphrase)
    encrypted = _xor_encrypt(text.encode("utf-8"), key)
    return base64.b64encode(encrypted).decode("ascii")


def _decrypt_text(encrypted_b64: str, passphrase: str) -> str:
    """解密 base64 加密文本"""
    key = _derive_key(passphrase)
    encrypted = base64.b64decode(encrypted_b64)
    decrypted = _xor_encrypt(encrypted, key)
    return decrypted.decode("utf-8")


class APIKeyManager:
    """
    API Key 管理器
    
    特性：
    - 支持 OpenAI / Kimi / 通义千问
    - 加密存储到本地文件
    - 轮询选取可用 key
    - 失败自动禁用（超过阈值）
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        passphrase: Optional[str] = None,
    ):
        self._keys: list[APIKeyEntry] = []
        self._round_robin_index = 0

        # 存储路径
        if storage_path:
            self._storage_path = Path(storage_path)
        else:
            self._storage_path = Path.home() / ".xhs-publisher" / "keys.enc"

        # 密码：优先参数 > 环境变量 > 默认
        self._passphrase = (
            passphrase
            or os.environ.get("XHS_KEY_PASSPHRASE", "")
            or "xhs-publisher-default-key"
        )

        # 尝试加载已有 key
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
    ) -> None:
        """添加一个 API Key"""
        provider = Provider(provider) if isinstance(provider, str) else provider
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
        轮询获取一个可用的 API Key
        
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

        # 轮询
        idx = self._round_robin_index % len(candidates)
        self._round_robin_index += 1
        entry = candidates[idx]
        entry.last_used = time.time()
        return entry

    def report_success(self, api_key: str) -> None:
        """报告调用成功，重置错误计数"""
        for k in self._keys:
            if k.api_key == api_key:
                k.error_count = 0
                k.enabled = True
                break

    def report_error(self, api_key: str) -> None:
        """报告调用失败，增加错误计数"""
        for k in self._keys:
            if k.api_key == api_key:
                k.error_count += 1
                if k.error_count >= k.max_errors:
                    k.enabled = False
                break

    def list_keys(self) -> list[dict]:
        """列出所有 key（脱敏）"""
        result = []
        for k in self._keys:
            masked = k.api_key[:8] + "****" + k.api_key[-4:] if len(k.api_key) > 12 else "****"
            result.append({
                "provider": k.provider.value,
                "key_masked": masked,
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
        从环境变量加载 API Key
        
        格式：
        - XHS_OPENAI_KEY=sk-xxx
        - XHS_KIMI_KEY=sk-xxx
        - XHS_QWEN_KEY=sk-xxx
        - XHS_OPENAI_BASE_URL=... (可选)
        - XHS_OPENAI_MODEL=... (可选)
        """
        count = 0
        env_map = {
            Provider.OPENAI: "XHS_OPENAI_KEY",
            Provider.KIMI: "XHS_KIMI_KEY",
            Provider.QWEN: "XHS_QWEN_KEY",
        }
        for provider, env_name in env_map.items():
            key = os.environ.get(env_name)
            if key:
                base_url = os.environ.get(f"XHS_{provider.value.upper()}_BASE_URL")
                model = os.environ.get(f"XHS_{provider.value.upper()}_MODEL")
                self.add_key(provider, key, base_url=base_url, model=model)
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
        """从文件解密加载"""
        if not self._storage_path.exists():
            return
        try:
            encrypted = self._storage_path.read_text(encoding="utf-8").strip()
            if not encrypted:
                return
            json_str = _decrypt_text(encrypted, self._passphrase)
            data = json.loads(json_str)
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
        except Exception:
            # 文件损坏或密码错误，忽略
            pass


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
    return _global_manager
