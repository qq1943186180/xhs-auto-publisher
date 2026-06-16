"""
小红书标题生成器
输入产品信息，输出多候选爆款标题
"""

import json
import re
import logging
from dataclasses import dataclass
from typing import Optional

from .prompt_templates import get_title_prompt
from .api_key_manager import get_key_manager, Provider

logger = logging.getLogger(__name__)
LLM_TIMEOUT_SECONDS = 20.0

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai 未安装，标题生成器将使用模板模式")


@dataclass
class TitleResult:
    """标题生成结果"""
    titles: list[str]
    provider: str
    model: str


# ============================================================
# 模板兜底（无 LLM 时使用）
# ============================================================

_TITLE_TEMPLATES = [
    "那天出门顺手戴了{name}",
    "最近常戴的一个小配饰",
    "{desc}，近看会更顺",
    "{name}不是第一眼，但耐看",
    "浅色衣服我会顺手配{name}",
    "试戴一下，发现比想象中好搭",
    "{name}这种安静一点的更耐留",
    "{desc}，不会太抢衣服",
]

_TITLE_REPLACEMENTS = {
    "绝绝子": "挺耐看",
    "真的绝": "挺耐看",
    "绝了": "不错",
    "闭眼入": "可以看看",
    "冲冲冲": "按需看",
    "冲": "看看",
    "天花板": "质感款",
    "被问爆": "有人问",
    "后悔没早买": "最近才注意到",
    "救命": "",
    "宝藏": "小众",
    "爱了爱了": "还挺喜欢",
}


def _soften_title(title: str) -> str:
    for old, new in _TITLE_REPLACEMENTS.items():
        title = title.replace(old, new)
    title = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", title)
    title = re.sub(r"[!！]{2,}", "。", title)
    title = re.sub(r"\s*[｜|]\s*", " ", title)
    title = re.sub(r"\s{2,}", " ", title)
    title = title.strip(" -｜|")
    return title


def _generate_from_templates(
    product_name: str,
    description: str,
    count: int = 5,
) -> list[str]:
    """模板模式生成标题（兜底）"""
    short_desc = description[:10] if description else "日常小物"
    results = []
    for tpl in _TITLE_TEMPLATES[:count]:
        title = _soften_title(tpl.format(name=product_name[:8], desc=short_desc))
        results.append(title)
    return results


# ============================================================
# LLM 标题生成
# ============================================================

def _call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: Optional[str] = None,
    provider: Optional[str | Provider] = None,
    temperature: float = 0.8,
) -> tuple[str, str, str]:
    """
    调用 LLM 获取回复
    返回: (response_text, provider_name, model_name)
    """
    if not HAS_OPENAI:
        raise ImportError("openai 包未安装")

    km = get_key_manager()
    entry = km.get_key(provider)

    if not entry:
        raise ValueError("没有可用的 API Key")

    client = OpenAI(
        api_key=api_key or entry.api_key,
        base_url=entry.base_url,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )

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
        km.report_success(entry.api_key)
        return text, entry.provider.value, entry.model
    except Exception as e:
        km.report_error(entry.api_key)
        raise


def _parse_titles(text: str) -> list[str]:
    """从 LLM 回复中解析标题列表"""
    lines = text.strip().split("\n")
    titles = []
    for line in lines:
        # 去除编号、前缀符号
        cleaned = re.sub(r"^[\d]+[\.\)、]\s*", "", line.strip())
        cleaned = re.sub(r"^[-•]\s*", "", cleaned)
        cleaned = _soften_title(cleaned)
        if cleaned and len(cleaned) >= 4:
            titles.append(cleaned)
    return titles


# ============================================================
# 公开 API
# ============================================================

def generate_titles(
    product_name: str,
    description: str,
    count: int = 5,
    extra_info: Optional[str] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> TitleResult:
    """
    生成小红书爆款标题
    
    Args:
        product_name: 产品名称
        description: 产品描述
        count: 候选标题数量
        extra_info: 补充信息（可选）
        provider: 指定 LLM 提供商（可选）
        api_key: 直接指定 API Key（可选）
    
    Returns:
        TitleResult 包含标题列表和调用信息
    """
    system_prompt, user_prompt = get_title_prompt(
        product_name=product_name,
        description=description,
        count=count,
        extra_info=extra_info,
    )

    # 尝试 LLM 生成
    try:
        text, provider_name, model_name = _call_llm(
            system_prompt, user_prompt, api_key=api_key, provider=provider
        )
        titles = _parse_titles(text)
        if titles:
            return TitleResult(
                titles=titles[:count],
                provider=provider_name,
                model=model_name,
            )
    except Exception as e:
        logger.warning(f"LLM 调用失败，回退到模板模式: {e}")

    # 兜底：模板生成
    titles = _generate_from_templates(product_name, description, count)
    return TitleResult(titles=titles, provider="template", model="template")
