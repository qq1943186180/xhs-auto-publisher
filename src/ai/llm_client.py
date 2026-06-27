"""
统一 LLM 调用客户端
从 title_generator._call_llm 抽取并增强：
- 指数退避重试（默认 2 次）
- 超时控制
- 错误分类（认证/限流/网络）
- 统一日志
- JSON 提取工具函数
"""

import json
import os
import re
import time
import logging
from typing import Optional

from .api_key_manager import get_key_manager, Provider

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 60.0


# ============================================================
# 自定义异常
# ============================================================

class AuthenticationError(Exception):
    """API Key 无效或认证失败"""
    pass


class RateLimitError(Exception):
    """请求被限流（429）"""
    pass


class NetworkError(Exception):
    """网络连接失败"""
    pass


# ============================================================
# 核心调用
# ============================================================

def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: Optional[str] = None,
    provider: Optional[str | Provider] = None,
    temperature: float = 0.8,
    max_retries: int = 2,
    timeout: float = LLM_TIMEOUT_SECONDS,
    max_tokens: Optional[int] = None,
) -> tuple[str, str, str]:
    """
    统一 LLM 调用入口，带指数退避重试。

    Returns:
        (response_text, provider_name, model_name)

    Raises:
        ImportError: openai 包未安装
        ValueError: 没有可用 API Key / LLM 返回空响应
        AuthenticationError: API Key 无效
        RateLimitError: 被限流
        NetworkError: 网络错误
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai 包未安装")

    km = get_key_manager()
    first_entry = km.get_key(provider)

    if not first_entry:
        raise ValueError("没有可用的 API Key")

    # 代理支持：环境变量 XHS_PROXY 或 HTTPS_PROXY
    http_client = None
    proxy = os.environ.get("XHS_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy:
        try:
            import httpx
            http_client = httpx.Client(proxy=proxy, timeout=timeout)
        except Exception:
            pass

    last_error = None
    tried_keys = set()
    pending_entries = [first_entry]
    if not api_key:
        for candidate in km.peek_keys(provider):
            if candidate.api_key != first_entry.api_key:
                pending_entries.append(candidate)

    for entry_index, entry in enumerate(pending_entries):
        if entry.api_key in tried_keys:
            continue
        tried_keys.add(entry.api_key)

        client = OpenAI(
            api_key=api_key or entry.api_key,
            base_url=entry.base_url,
            timeout=timeout,
            max_retries=0,
            http_client=http_client,
        )

        attempts_for_entry = max_retries + 1 if entry_index == 0 else 1
        for attempt in range(attempts_for_entry):
            retry_label = f"{attempt + 1}/{attempts_for_entry}"
            try:
                resp = client.chat.completions.create(
                    model=entry.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens if max_tokens is not None else entry.max_tokens,
                    temperature=temperature,
                )
                text = resp.choices[0].message.content.strip()
                if not text:
                    raise ValueError("LLM 返回空响应")
                km.report_success(entry.api_key)
                return text, entry.provider.value, entry.model

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # 分类错误
                if "401" in error_str or "unauthorized" in error_str or "invalid" in error_str:
                    km.report_error(entry.api_key, permanent=True)
                    if not api_key and entry_index < len(pending_entries) - 1:
                        logger.warning(
                            "%s API Key 认证失败，已禁用并切换下一个可用 Key: %s",
                            entry.provider.value,
                            e,
                        )
                        break
                    raise AuthenticationError(f"API Key 认证失败: {e}") from e

                if "429" in error_str or "rate" in error_str or "too many" in error_str:
                    if attempt < attempts_for_entry - 1:
                        wait = 2 ** attempt * 2
                        logger.warning("限流，%ss 后重试 (%s): %s", wait, retry_label, e)
                        time.sleep(wait)
                        continue
                    if not api_key and entry_index < len(pending_entries) - 1:
                        logger.warning("%s 被限流，切换下一个可用 Key", entry.provider.value)
                        break
                    raise RateLimitError(f"请求被限流: {e}") from e

                if "timeout" in error_str or "connect" in error_str or "network" in error_str:
                    if attempt < attempts_for_entry - 1:
                        wait = 2 ** attempt
                        logger.warning("网络错误，%ss 后重试 (%s): %s", wait, retry_label, e)
                        time.sleep(wait)
                        continue
                    if not api_key and entry_index < len(pending_entries) - 1:
                        logger.warning("%s 网络错误，切换下一个可用 Key", entry.provider.value)
                        break
                    raise NetworkError(f"网络错误: {e}") from e

                # 其他错误：重试一次
                km.report_error(entry.api_key)
                if attempt < attempts_for_entry - 1:
                    wait = 2 ** attempt
                    logger.warning("调用失败，%ss 后重试 (%s): %s", wait, retry_label, e)
                    time.sleep(wait)
                    continue
                if not api_key and entry_index < len(pending_entries) - 1:
                    logger.warning("%s 调用失败，切换下一个可用 Key: %s", entry.provider.value, e)
                    break
                raise

    # 所有候选 key 都失败
    if last_error:
        error_str = str(last_error).lower()
        if "401" in error_str or "unauthorized" in error_str or "invalid" in error_str:
            raise AuthenticationError(f"API Key 认证失败: {last_error}") from last_error
        if "429" in error_str or "rate" in error_str or "too many" in error_str:
            raise RateLimitError(f"请求被限流: {last_error}") from last_error
        if "timeout" in error_str or "connect" in error_str or "network" in error_str:
            raise NetworkError(f"网络错误: {last_error}") from last_error
        raise last_error

    raise ValueError("LLM 调用失败")


# ============================================================
# JSON 提取工具
# ============================================================

def extract_json(text: str) -> dict:
    """
    从 LLM 回复中提取 JSON。
    尝试顺序：直接解析 → ```json``` 代码块 → 首尾花括号 → 截断修复。
    """
    text = text.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Caught json, continuing")
    # 尝试提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            logger.debug("Caught json, continuing")
    # 尝试找到第一个 { 和最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            logger.debug("Caught json, continuing")

    # 尝试修复截断的 JSON：补全未闭合的 { 和 [
    if start != -1:
        truncated = text[start:]
        repaired = _try_repair_truncated_json(truncated)
        if repaired is not None:
            logger.info("成功修复截断的 JSON（长度 %d → %d）", len(truncated), len(repaired))
            return repaired

    raise ValueError(f"无法从 LLM 回复中提取 JSON: {text[:200]}...")


def _try_repair_truncated_json(text: str) -> Optional[dict]:
    """
    尝试修复被截断的 JSON 文本。
    策略：逐步去掉未闭合的字符串/数组/对象尾部，补全括号后尝试解析。
    """
    # 策略1: 找到最后一个完整的元素，截断到那里并闭合
    # 先去掉末尾不完整的字符串值（截断在最后一个完整的 " 处）
    candidates = []
    posts_match = re.search(r'("posts"\s*:\s*\[)', text)
    if posts_match:
        last_obj = text.rfind("}")
        if last_obj > posts_match.end():
            candidates.append(text[:last_obj + 1] + "]}")

    # 尝试在最后一个完整的 } 或 ] 之后截断
    for close_char in ('}', ']'):
        idx = text.rfind(close_char)
        if idx > 0:
            candidate = text[:idx + 1]
            candidates.append(candidate)

    # 尝试在最后一个完整的 " 之后截断（处理字符串被截断的情况）
    last_quote = text.rfind('"')
    if last_quote > 0:
        # 检查这个引号是否被转义
        num_backslashes = 0
        i = last_quote - 1
        while i >= 0 and text[i] == '\\':
            num_backslashes += 1
            i -= 1
        if num_backslashes % 2 == 0:  # 未转义的引号
            candidate = text[:last_quote + 1]
            candidates.append(candidate)

    for candidate in candidates:
        # 统计未闭合的括号
        open_braces = 0
        open_brackets = 0
        in_string = False
        escape_next = False

        for ch in candidate:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                open_braces += 1
            elif ch == '}':
                open_braces -= 1
            elif ch == '[':
                open_brackets += 1
            elif ch == ']':
                open_brackets -= 1

        # 如果字符串未闭合，加上闭合引号
        if in_string:
            candidate += '"'

        # 去掉末尾的逗号（JSON 不允许尾部逗号）
        candidate = candidate.rstrip()
        while candidate.endswith(','):
            candidate = candidate[:-1].rstrip()

        # 补全未闭合的括号
        closers = ']' * max(0, open_brackets) + '}' * max(0, open_braces)
        repaired = candidate + closers

        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            continue

    return None
