"""
方向生成器（第一轮）
输入产品信息，输出 3 个差异化内容方向
"""

import logging
from dataclasses import dataclass
from typing import Optional

from .prompt_templates import get_direction_prompt
from .llm_client import call_llm, extract_json

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
# 兜底方向（按产品类别映射，无 LLM 时使用）
# ============================================================

_DEFAULT_DIRECTIONS = [
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

# 按产品类别映射的兜底方向
_CATEGORY_DIRECTIONS = {
    "护肤": [
        {"id": "A", "name": "日常护肤记录", "target_audience": "注重护肤的年轻女性", "angle": "记录早晚护肤步骤中产品的真实使用感受", "hook_type": "日常记录", "style_hint": "真实体验，不夸大功效"},
        {"id": "B", "name": "成分党观察", "target_audience": "关注成分的理性消费者", "angle": "从成分表出发分析适合什么肤质", "hook_type": "成分分析", "style_hint": "客观分析，具体描述"},
        {"id": "C", "name": "换季适配", "target_audience": "季节性皮肤困扰人群", "angle": "换季时的使用感受和搭配建议", "hook_type": "季节场景", "style_hint": "时令感，具体场景"},
    ],
    "数码": [
        {"id": "A", "name": "通勤使用体验", "target_audience": "上班族/通勤族", "angle": "日常通勤中的真实使用场景", "hook_type": "日常场景", "style_hint": "真实使用，不过度吹捧"},
        {"id": "B", "name": "与同类对比", "target_audience": "有选择困难的消费者", "angle": "和市面上同类产品的差异点", "hook_type": "对比选择", "style_hint": "客观对比，说取舍"},
        {"id": "C", "name": "小众用法发现", "target_audience": "喜欢探索新用法的人", "angle": "发现产品的一个意外好用的场景", "hook_type": "发现记录", "style_hint": "轻松分享，有惊喜感"},
    ],
    "食品": [
        {"id": "A", "name": "日常零食记录", "target_audience": "爱吃零食的年轻人", "angle": "某个下午或追剧时顺手吃的场景", "hook_type": "日常场景", "style_hint": "轻松随意，像在聊天"},
        {"id": "B", "name": "送礼/分享场景", "target_audience": "有送礼需求的人", "angle": "送朋友或一起分享时的感受", "hook_type": "分享过程", "style_hint": "温暖自然，不煽情"},
        {"id": "C", "name": "口味细节", "target_audience": "注重口感的人", "angle": "描述具体口味、口感和层次", "hook_type": "细节观察", "style_hint": "具体描述，像在讲给朋友听"},
    ],
}


def _generate_fallback_directions(product_name: str, category: str = "") -> list[Direction]:
    """生成兜底方向，优先根据类别映射，否则使用默认方向"""
    # 尝试类别匹配
    if category:
        for key, dirs in _CATEGORY_DIRECTIONS.items():
            if key in category:
                return [Direction(**d) for d in dirs]
    # 默认方向
    return [Direction(**d) for d in _DEFAULT_DIRECTIONS]


# ============================================================
# 解析工具
# ============================================================

def _parse_directions(data: dict) -> list[Direction]:
    """从 JSON 解析方向列表，对关键字段做非空校验"""
    directions = []
    for d in data.get("directions", []):
        dir_id = d.get("id", "").strip()
        name = d.get("name", "").strip()
        # 关键字段非空校验
        if not dir_id or not name:
            logger.warning("跳过无效方向: id=%s, name=%s", dir_id, name)
            continue
        directions.append(Direction(
            id=dir_id,
            name=name,
            target_audience=d.get("target_audience", "").strip(),
            angle=d.get("angle", "").strip(),
            hook_type=d.get("hook_type", "").strip(),
            style_hint=d.get("style_hint", "").strip(),
        ))
    return directions


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
        text, provider_name, model_name = call_llm(
            system_prompt, user_prompt,
            api_key=api_key,
            provider=provider,
            temperature=0.7,  # 第一轮低温度保证方向质量
        )
        raw_json = extract_json(text)
        directions = _parse_directions(raw_json)
        if len(directions) >= 2:
            return DirectionResult(
                directions=directions[:3],
                raw_json=raw_json,
                provider=provider_name,
                model=model_name,
            )
        logger.warning("LLM 返回方向数量不足 (%s)，使用兜底", len(directions))
    except Exception as e:
        logger.warning("方向生成 LLM 调用失败，使用兜底: %s", e)

    # 兜底
    directions = _generate_fallback_directions(product_name, style)
    return DirectionResult(
        directions=directions,
        raw_json={"directions": [d.__dict__ for d in directions]},
        provider="template",
        model="template",
    )
