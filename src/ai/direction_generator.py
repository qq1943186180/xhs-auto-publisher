"""
方向生成器（第一轮）
输入产品信息，输出 3 个差异化内容方向
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .prompt_templates import get_direction_prompt
from .api_key_manager import get_key_manager
from .title_generator import _call_llm

logger = logging.getLogger(__name__)


@dataclass
class Direction:
    """单个内容方向"""
    id: str               # A/B/C
    name: str             # 方向名称
    target_audience: str  # 目标人群
    angle: str            # 内容角度
    hook_type: str        # 钩子类型
    style_hint: str       # 风格提示


@dataclass
class DirectionResult:
    """方向生成结果"""
    directions: list[Direction]
    raw_json: dict        # 原始 JSON 响应
    provider: str
    model: str


# ============================================================
# 兜底方向（无 LLM 时使用）
# ============================================================

_FALLBACK_DIRECTIONS = [
    {
        "id": "A",
        "name": "日常搭配",
        "target_audience": "喜欢简洁穿搭的年轻女性",
        "angle": "从日常衣服和场景里带出配饰存在感",
        "hook_type": "场景记录",
        "style_hint": "克制分享，突出搭配细节",
    },
    {
        "id": "B",
        "name": "送礼参考",
        "target_audience": "有送礼需求的人群",
        "angle": "以送礼选择和日常适配度切入",
        "hook_type": "选择过程",
        "style_hint": "自然故事体，不煽情",
    },
    {
        "id": "C",
        "name": "细节观察",
        "target_audience": "注重质感和细节的人群",
        "angle": "观察材质、颜色、做工和佩戴效果",
        "hook_type": "细节记录",
        "style_hint": "具体、平实，少下结论",
    },
]


def _generate_fallback_directions(product_name: str) -> list[Direction]:
    """生成兜底方向"""
    return [Direction(**d) for d in _FALLBACK_DIRECTIONS]


# ============================================================
# LLM 方向生成
# ============================================================

def _parse_directions(data: dict) -> list[Direction]:
    """从 JSON 解析方向列表"""
    directions = []
    for d in data.get("directions", []):
        directions.append(Direction(
            id=d.get("id", ""),
            name=d.get("name", ""),
            target_audience=d.get("target_audience", ""),
            angle=d.get("angle", ""),
            hook_type=d.get("hook_type", ""),
            style_hint=d.get("style_hint", ""),
        ))
    return directions


def _extract_json(text: str) -> dict:
    """从 LLM 回复中提取 JSON"""
    text = text.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取 ```json ... ``` 块
    import re
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试找到第一个 { 和最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法从 LLM 回复中提取 JSON: {text[:200]}...")


# ============================================================
# 公开 API
# ============================================================

def generate_directions(
    product_name: str,
    description: str,
    price: str = "未知",
    selling_points: str = "",
    style: str = "种草推荐",
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> DirectionResult:
    """
    第一轮：生成 3 个差异化内容方向
    
    Args:
        product_name: 产品名称
        description: 产品描述
        price: 产品价格
        selling_points: 核心卖点
        provider: 指定 LLM 提供商
        api_key: 直接指定 API Key
    
    Returns:
        DirectionResult
    """
    system_prompt, user_prompt = get_direction_prompt(
        product_name=product_name,
        description=description,
        price=price,
        selling_points=selling_points,
        style=style,
    )

    # 尝试 LLM 生成
    try:
        text, provider_name, model_name = _call_llm(
            system_prompt, user_prompt,
            api_key=api_key,
            provider=provider,
            temperature=0.7,  # 第一轮低温度保证方向质量
        )
        raw_json = _extract_json(text)
        directions = _parse_directions(raw_json)
        if len(directions) >= 2:
            return DirectionResult(
                directions=directions[:3],
                raw_json=raw_json,
                provider=provider_name,
                model=model_name,
            )
        logger.warning(f"LLM 返回方向数量不足 ({len(directions)})，使用兜底")
    except Exception as e:
        logger.warning(f"方向生成 LLM 调用失败，使用兜底: {e}")

    # 兜底
    directions = _generate_fallback_directions(product_name)
    return DirectionResult(
        directions=directions,
        raw_json={"directions": _FALLBACK_DIRECTIONS},
        provider="template",
        model="template",
    )
