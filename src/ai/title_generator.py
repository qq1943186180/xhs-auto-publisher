"""
小红书标题生成器
输入产品信息，输出多候选爆款标题
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

from .prompt_templates import get_title_prompt
from .llm_client import call_llm
from .text_cleaner import soften_title

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI  # noqa: F401 — 保留兼容导入
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


def _generate_from_templates(
    product_name: str,
    description: str,
    count: int = 5,
) -> list[str]:
    """模板模式生成标题（兜底）"""
    short_desc = description[:10] if description else "日常小物"
    results = []
    for tpl in _TITLE_TEMPLATES[:count]:
        title = soften_title(tpl.format(name=product_name[:8], desc=short_desc))
        results.append(title)
    return results


# ============================================================
# 解析工具
# ============================================================

def _parse_titles(text: str) -> list[str]:
    """从 LLM 回复中解析标题列表"""
    lines = text.strip().split("\n")
    titles = []
    for line in lines:
        # 去除编号、前缀符号
        cleaned = re.sub(r"^[\d]+[\.\)、]\s*", "", line.strip())
        cleaned = re.sub(r"^[-•]\s*", "", cleaned)
        cleaned = soften_title(cleaned)
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
        text, provider_name, model_name = call_llm(
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
        logger.warning("LLM 调用失败，回退到模板模式: %s", e)

    # 兜底：模板生成
    titles = _generate_from_templates(product_name, description, count)
    return TitleResult(titles=titles, provider="template", model="template")
