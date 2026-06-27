"""User-facing error message helpers."""

from __future__ import annotations

import re


_CLOUDFLARE_KEYWORDS = ("cloudflare", "拦截", "access denied", "blocked")


def is_cloudflare_error(text: str) -> bool:
    """Check if an error message indicates a Cloudflare/blocking issue."""
    if not text:
        return False
    lower = text.lower()
    return any(kw in lower for kw in _CLOUDFLARE_KEYWORDS)


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"nvapi-[A-Za-z0-9_-]{12,}"),
]


def redact_sensitive(text: object) -> str:
    """Mask API keys and other token-looking values before showing text in UI."""
    value = "" if text is None else str(text)
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(lambda m: m.group(0)[:6] + "..." + m.group(0)[-4:], value)
    return value


def explain_error(error: object) -> str:
    """Convert a raw technical error into a short, actionable Chinese message."""
    raw = redact_sensitive(error).strip()
    lower = raw.lower()

    if not raw:
        return "操作失败，但没有返回具体原因。可以稍后重试，或查看日志。"

    if "cloudflare" in lower or "access denied" in lower or "ray id" in lower or "被 cloudflare" in lower:
        return f"ChatGPT 被 Cloudflare 拦截。请更换代理/VPN 后重试。原始信息：{raw}"

    if "not logged in" in lower or "login timeout" in lower or "未登录" in raw or "登录" in raw and "超时" in raw:
        return f"账号登录状态不可用。请在浏览器里重新登录后再试。原始信息：{raw}"

    if "no valid image" in lower or "file input not found" in lower or "upload" in lower or "图片上传" in raw:
        return f"图片上传失败。请确认图片文件还存在、格式正常，然后重试。原始信息：{raw}"

    if "没有可用" in raw and "api key" in lower or "api key" in lower and ("invalid" in lower or "unauthorized" in lower or "401" in lower):
        return f"API Key 不可用。请到设置页检查 Key、Base URL 和模型名称。原始信息：{raw}"

    if "429" in lower or "rate" in lower or "too many" in lower or "限流" in raw:
        return f"模型接口被限流。请稍后重试，或切换备用模型。原始信息：{raw}"

    if "connection error" in lower or "network" in lower or "timeout" in lower or "timed out" in lower or "502" in lower:
        return f"网络连接不稳定或服务超时。请检查代理/网络后重试。原始信息：{raw}"

    if "无法从 llm 回复中提取 json" in raw.lower() or "json" in lower:
        return f"模型返回格式不完整，已尝试修复或回退模板。原始信息：{raw}"

    return raw


def summarize_errors(errors: list[object], max_items: int = 5) -> str:
    messages = []
    for error in errors or []:
        message = explain_error(error)
        if message and message not in messages:
            messages.append(message)
        if len(messages) >= max_items:
            break
    return "\n".join(messages)
