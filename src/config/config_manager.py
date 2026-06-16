import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "app": {
        "name": "xhs-auto-publisher",
        "version": "1.0.0",
        "language": "zh_CN",
        "theme": "light",
    },
    "database": {
        "path": "~/.xhs-publisher/data.db",
    },
    "collector": {
        "images_per_product": 5,
    },
    "xhs": {
        "cookie": "",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "proxy": "",
        "timeout": 30,
    },
    "publish": {
        "interval_seconds": 300,
        "max_daily_posts": 10,
        "auto_retry": True,
        "max_retries": 3,
        "retry_delay_seconds": 60,
        "random_delay_min": 5,
        "random_delay_max": 30,
    },
    "notification": {
        "enabled": False,
        "webhook_url": "",
        "notify_on_success": True,
        "notify_on_failure": True,
    },
    "log": {
        "level": "INFO",
        "max_file_size_mb": 10,
        "backup_count": 5,
        "console_output": True,
    },
}


ENV_OVERRIDES = {
    "XHS_COOKIE": "xhs.cookie",
    "XHS_PROXY": "xhs.proxy",
    "XHS_PUBLISH_INTERVAL_SECONDS": "publish.interval_seconds",
    "XHS_MAX_DAILY_POSTS": "publish.max_daily_posts",
    "XHS_LOG_LEVEL": "log.level",
    "XHS_NOTIFICATION_WEBHOOK_URL": "notification.webhook_url",
}


def _simple_encrypt(text: str) -> str:
    """Small obfuscation for locally stored sensitive fields."""
    if not text:
        return ""
    shifted = "".join(chr((ord(c) + 3) % 65536) for c in text)
    return base64.b64encode(shifted.encode("utf-8")).decode("utf-8")


def _simple_decrypt(encoded: str) -> str:
    if not encoded:
        return ""
    try:
        shifted = base64.b64decode(encoded.encode("utf-8")).decode("utf-8")
        return "".join(chr((ord(c) - 3) % 65536) for c in shifted)
    except Exception:
        return encoded


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class ConfigManager:
    """Load app config from defaults, JSON config, then environment variables."""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_dir = Path.home() / ".xhs-publisher"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = str(config_dir / "config.json")

        self.config_path = config_path
        self._config = {}
        self._encrypted_keys = {"xhs.cookie", "notification.webhook_url"}
        self.load()

    def load(self):
        self._config = json.loads(json.dumps(DEFAULT_CONFIG))

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                self._config = _deep_merge(self._config, file_config)
                logger.info("Config loaded: %s", self.config_path)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Config load failed: %s", e)

        for key_path in self._encrypted_keys:
            val = self.get(key_path)
            if val:
                self.set(key_path, _simple_decrypt(val), save=False)

        self._load_env_overrides()

    def save(self):
        save_config = json.loads(json.dumps(self._config))
        for key_path in self._encrypted_keys:
            parts = key_path.split(".")
            obj = save_config
            for part in parts[:-1]:
                obj = obj.get(part, {})
            if parts[-1] in obj and obj[parts[-1]]:
                obj[parts[-1]] = _simple_encrypt(obj[parts[-1]])

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(save_config, f, indent=2, ensure_ascii=False)
            logger.info("Config saved: %s", self.config_path)
        except IOError as e:
            logger.error("Config save failed: %s", e)

    def get(self, key_path: str, default: Any = None) -> Any:
        parts = key_path.split(".")
        config = self._config
        for part in parts:
            if isinstance(config, dict) and part in config:
                config = config[part]
            else:
                return default
        return config

    def set(self, key_path: str, value: Any, save: bool = True):
        parts = key_path.split(".")
        config = self._config
        for part in parts[:-1]:
            if part not in config:
                config[part] = {}
            config = config[part]
        config[parts[-1]] = value

        if save:
            self.save()

    def get_section(self, section: str) -> dict:
        return self._config.get(section, {})

    def reload(self):
        self.load()

    def reset(self):
        self._config = json.loads(json.dumps(DEFAULT_CONFIG))
        self.save()

    def _load_env_overrides(self):
        for env_name, key_path in ENV_OVERRIDES.items():
            if env_name in os.environ:
                self.set(key_path, self._cast_value(os.environ[env_name]), save=False)

    @staticmethod
    def _cast_value(value: str) -> Any:
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value


_config_manager: ConfigManager = None


def get_config_manager(config_path: str = None) -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_path)
    return _config_manager
