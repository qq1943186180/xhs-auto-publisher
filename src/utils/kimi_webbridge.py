"""
Kimi WebBridge lifecycle helpers.

The image generator depends on the local Kimi WebBridge daemon.  This module
keeps startup idempotent and handles the common stale pid-file state observed
on Windows after the daemon exits unexpectedly.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_COMMAND_URL = "http://127.0.0.1:10086/command"
DEFAULT_STATUS_URL = "http://127.0.0.1:10086/status"


@dataclass
class KimiWebBridgeStatus:
    running: bool = False
    extension_connected: bool = False
    message: str = ""
    port: int | None = None
    pid: int | None = None
    version: str = ""
    extension_version: str = ""
    binary_path: str = ""
    started: bool = False
    stale_pid_removed: int | None = None
    update_available: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.running and self.extension_connected


def command_url() -> str:
    return os.environ.get("KIMI_WEBBRIDGE_URL", DEFAULT_COMMAND_URL)


def status_url() -> str:
    url = command_url()
    if "/command" in url:
        return url.rsplit("/command", 1)[0] + "/status"
    return os.environ.get("KIMI_WEBBRIDGE_STATUS_URL", DEFAULT_STATUS_URL)


def _home_binary() -> Path:
    exe_name = "kimi-webbridge.exe" if sys.platform == "win32" else "kimi-webbridge"
    return Path.home() / ".kimi-webbridge" / "bin" / exe_name


def find_kimi_binary() -> Path | None:
    env_path = os.environ.get("KIMI_WEBBRIDGE_BIN")
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(_home_binary())

    path_binary = shutil.which("kimi-webbridge")
    if path_binary:
        candidates.append(Path(path_binary))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _pid_file() -> Path:
    return Path.home() / ".kimi-webbridge" / "daemon.pid"


def _pid_is_running(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return True

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _remove_stale_pid_file(logger: logging.Logger | None = None) -> int | None:
    pid_file = _pid_file()
    if not pid_file.exists():
        return None

    try:
        pid_text = pid_file.read_text(encoding="utf-8").strip()
        if not pid_text.isdigit():
            return None
        pid = int(pid_text)
        if _pid_is_running(pid):
            return None
        pid_file.unlink()
        if logger:
            logger.warning("Kimi WebBridge stale pid file removed: %s", pid)
        return pid
    except Exception as exc:
        if logger:
            logger.warning("Failed to inspect Kimi WebBridge pid file: %s", exc)
        return None


def read_kimi_status(timeout: float = 3) -> KimiWebBridgeStatus:
    try:
        with urllib.request.urlopen(status_url(), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return KimiWebBridgeStatus(
            running=False,
            message=f"Kimi WebBridge 未启动或无法连接：{exc}",
        )

    return KimiWebBridgeStatus(
        running=bool(data.get("running")),
        extension_connected=bool(data.get("extension_connected")),
        message="",
        port=data.get("port"),
        pid=data.get("pid"),
        version=str(data.get("version") or ""),
        extension_version=str(data.get("extension_version") or ""),
        update_available=data.get("update_available") or {},
        raw=data,
    )


def describe_kimi_status(status: KimiWebBridgeStatus) -> str:
    if status.ready:
        suffix = ""
        update = status.update_available or {}
        latest = update.get("latest")
        current = update.get("current")
        if latest and current and latest != current:
            suffix = f"（可稍后更新 {current} -> {latest}）"
        return f"Kimi WebBridge 已连接，可用于 ChatGPT 生图{suffix}"

    if status.running and not status.extension_connected:
        return "Kimi WebBridge 服务已启动，但浏览器扩展未连接。请打开已安装扩展的 Edge/Chrome 后重试生图。"

    return status.message or "Kimi WebBridge 未启动，无法连接 ChatGPT 生图。"


def _start_daemon(binary: Path, timeout: float = 15) -> subprocess.CompletedProcess:
    kwargs = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run([str(binary), "start"], **kwargs)


def ensure_kimi_webbridge(
    start_if_needed: bool = True,
    wait_seconds: float = 8,
    logger: logging.Logger | None = None,
) -> KimiWebBridgeStatus:
    """Return current daemon status, starting it when possible."""
    current = read_kimi_status()
    if current.ready or current.running or not start_if_needed:
        current.message = describe_kimi_status(current)
        return current

    binary = find_kimi_binary()
    if not binary:
        current.message = (
            "未找到 Kimi WebBridge 启动文件。请安装 Kimi WebBridge，"
            "或设置 KIMI_WEBBRIDGE_BIN 指向 kimi-webbridge.exe。"
        )
        return current

    stale_pid = _remove_stale_pid_file(logger)
    try:
        result = _start_daemon(binary)
    except Exception as exc:
        return KimiWebBridgeStatus(
            running=False,
            message=f"Kimi WebBridge 启动失败：{exc}",
            binary_path=str(binary),
            stale_pid_removed=stale_pid,
        )

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        retry_stale_pid = _remove_stale_pid_file(logger)
        if retry_stale_pid is not None:
            stale_pid = retry_stale_pid
            try:
                result = _start_daemon(binary)
                stderr = (result.stderr or result.stdout or "").strip()
            except Exception as exc:
                return KimiWebBridgeStatus(
                    running=False,
                    message=f"Kimi WebBridge 启动失败：{exc}",
                    binary_path=str(binary),
                    stale_pid_removed=stale_pid,
                )
        if result.returncode != 0:
            return KimiWebBridgeStatus(
                running=False,
                message=f"Kimi WebBridge 启动失败：{stderr or '未知错误'}",
                binary_path=str(binary),
                stale_pid_removed=stale_pid,
            )

    deadline = time.time() + wait_seconds
    latest = KimiWebBridgeStatus(
        running=False,
        message="Kimi WebBridge 正在启动，但暂时还未响应。",
        binary_path=str(binary),
        started=True,
        stale_pid_removed=stale_pid,
    )
    while time.time() < deadline:
        latest = read_kimi_status(timeout=2)
        latest.binary_path = str(binary)
        latest.started = True
        latest.stale_pid_removed = stale_pid
        if latest.ready:
            break
        if latest.running and not latest.extension_connected:
            time.sleep(0.5)
            continue
        time.sleep(0.5)

    latest.message = describe_kimi_status(latest)
    return latest
