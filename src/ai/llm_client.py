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
import re
import time
import logging
from typing import Optional

from .api_key_manager import get_key_manager, Provider

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 20.0


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
    entry = km.get_key(provider)

    if not entry:
        raise ValueError("没有可用的 API Key")

    client = OpenAI(
        api_key=api_key or entry.api_key,
        base_url=entry.base_url,
        timeout=timeout,
        max_retries=0,  # 我们自己管理重试
    )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=entry.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=entry.max_tokens,
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
                raise AuthenticationError(f"API Key 认证失败: {e}") from e

            if "429" in error_str or "rate" in error_str or "too many" in error_str:
                km.report_error(entry.api_key)
                if attempt < max_retries:
                    wait = 2 ** attempt * 2
                    logger.warning("限流，%ss 后重试 (%s/%s)", wait, attempt + 1, max_retries)
                    time.sleep(wait)
                    continue
                raise RateLimitError(f"请求被限流: {e}") from e

            if "timeout" in error_str or "connect" in error_str or "network" in error_str:
                km.report_error(entry.api_key)
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning("网络错误，%ss 后重试 (%s/%s)", wait, attempt + 1, max_retries)
                    time.sleep(wait)
                    continue
                raise NetworkError(f"网络错误: {e}") from e

            # 其他错误：重试一次
            km.report_error(entry.api_key)
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("调用失败，%ss 后重试 (%s/%s): %s", wait, attempt + 1, max_retries, e)
                time.sleep(wait)
                continue
            raise

    # 所有重试用尽
    raise last_error or ValueError("LLM 调用失败")


# ============================================================
# JSON 提取工具
# ============================================================

def extract_json(text: str) -> dict:
    """
    从 LLM 回复中提取 JSON。
    尝试顺序：直接解析 → ```json``` 代码块 → 首尾花括号。
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
    raise ValueError(f"无法从 LLM 回复中提取 JSON: {text[:200]}...")
