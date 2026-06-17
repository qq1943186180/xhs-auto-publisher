"""
小红书文案生成器
支持种草/测评/教程三种风格
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from .prompt_templates import (
    STYLE_ALIASES,
    get_content_prompt,
    get_tags_prompt,
    get_direction_content_prompt,
)
from .llm_client import call_llm, extract_json
from .text_cleaner import soften_ai_style, soften_story_title

logger = logging.getLogger(__name__)


@dataclass
class ContentResult:
    """文案生成结果"""
    content: str          # 笔记正文
    tags: list[str]       # 话题标签列表
    style: str            # 使用的风格
    provider: str         # LLM 提供商
    model: str            # 模型名称


@dataclass
class DirectionPost:
    """单篇方向文案"""
    index: int            # 序号 1-9
    direction_id: str     # 所属方向 A/B/C
    direction_name: str   # 方向名称
    hook_style: str       # 开头风格
    title: str            # 标题
    content: str          # 正文
    tags: list[str]       # 话题标签


@dataclass
class DirectionContentResult:
    """方向扩写结果（一个方向的 3 篇）"""
    direction_id: str
    direction_name: str
    posts: list[DirectionPost]
    provider: str
    model: str


# ============================================================
# 模板兜底
# ============================================================

_CONTENT_TEMPLATES = {
    "种草": """那天出门前临时把衬衫换成了浅一点的颜色，手边刚好放着这个{name}，就顺手戴上了。

原本没指望它有多抢眼，但走到窗边照一下，{desc}，细节反而是在近看时才慢慢出来的。它不会一下把整套穿搭拉得很满，这点我还挺喜欢。

我那天戴着它出门，最大的感觉是很省心，不需要特地为了它改别的配饰。小缺点也有，就是光线暗一点的时候存在感会弱下来，拍照得靠近窗边。

所以它更像一件会被反复顺手拿起的东西，不是第一眼惊艳，但会让人慢慢记住。

#日常穿搭 #配饰分享 #小众配饰 #好物记录""",

    "测评": """我现在看这类配饰，不太会先看它亮不亮，反而会先看戴上去会不会显得太用力。

这条{name}上手的时候，{desc}。第一眼不是特别炸，但靠近看会发现细节比远看更顺，属于那种不需要解释、自己能慢慢加分的款。

我后来特地拿它配了两身衣服试了一下，白衬衫和浅针织都能接得住，说明它的适配度还不错。真要说取舍，就是它不太适合那种本来就很强势的穿搭，气质会偏安静。

如果你平时挑东西更在意细节和耐看度，这种会比那种一眼很亮的款更耐留。

#配饰测评 #日常好物 #穿搭细节 #小众审美""",

    "教程": """我后来发现这类{name}要戴得自然，重点不是叠多少，而是先把旁边的东西收一收。

比如衣服颜色别太杂，白色、米色、浅灰这类会更稳。{desc}，所以它本身已经有细节的话，旁边就别再堆太多复杂元素，不然容易互相抢。

拍照也一样，我更喜欢站到窗边，手里顺便拿个杯子或者整理一下袖口，比专门摆拍自然很多。这样拍出来会像真的在过日子，不像为了展示配饰硬拍。

如果要再加一点别的配饰，我通常只会留一条很细的素链，重点还是让画面留白一点。

#配饰搭配 #穿搭思路 #日常穿搭 #拍照小技巧""",
}


# ============================================================
# 解析工具
# ============================================================

_TAG_PATTERN = re.compile(r"#[\u4e00-\u9fa5a-zA-Z0-9_]+")


def _extract_and_parse_tags(text: str) -> tuple[str, list[str]]:
    """从正文中分离出正文和话题标签，合并了 _extract_tags 和 _parse_tags"""
    tags = _TAG_PATTERN.findall(text)

    # 移除纯标签行（标签占行大部分内容时跳过该行）
    lines = text.strip().split("\n")
    content_lines = []
    for line in lines:
        if _TAG_PATTERN.search(line) and len(line) - len("".join(_TAG_PATTERN.findall(line))) < 10:
            continue
        content_lines.append(line)

    content = "\n".join(content_lines).strip()
    return content, tags[:5] if tags else []


def _normalize_story_style(style: str) -> str:
    return STYLE_ALIASES.get(style, "种草")


# ============================================================
# 模板兜底生成
# ============================================================

def _generate_from_template(
    product_name: str,
    description: str,
    style: str = "种草",
) -> ContentResult:
    """模板模式生成文案（兜底）"""
    tpl = _CONTENT_TEMPLATES.get(_normalize_story_style(style), _CONTENT_TEMPLATES["种草"])
    content = soften_ai_style(tpl.format(name=product_name, desc=description[:50]))

    tags = [
        f"#{product_name}",
        "#日常穿搭",
        "#配饰分享",
        "#好物记录",
    ]

    return ContentResult(
        content=content,
        tags=tags,
        style=style,
        provider="template",
        model="template",
    )


# ============================================================
# 公开 API
# ============================================================

def generate_content(
    product_name: str,
    description: str,
    title: str,
    price: str = "未知",
    selling_points: str = "",
    style: str = "种草",
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> ContentResult:
    """
    生成小红书笔记正文

    Args:
        product_name: 产品名称
        description: 产品描述
        title: 笔记标题
        price: 产品价格
        selling_points: 核心卖点
        style: 风格（种草/测评/教程）
        provider: 指定 LLM 提供商
        api_key: 直接指定 API Key

    Returns:
        ContentResult
    """
    price = price or "未知"
    selling_points = selling_points or ""

    system_prompt, user_prompt = get_content_prompt(
        product_name=product_name,
        description=description,
        title=title,
        price=price,
        selling_points=selling_points,
        style=style,
    )

    # 尝试 LLM 生成
    try:
        text, provider_name, model_name = call_llm(
            system_prompt, user_prompt, api_key=api_key, provider=provider
        )
        content, tags = _extract_and_parse_tags(text)
        return ContentResult(
            content=soften_ai_style(content),
            tags=tags[:5],
            style=style,
            provider=provider_name,
            model=model_name,
        )
    except Exception as e:
        logger.warning("LLM 调用失败，回退到模板模式: %s", e)

    return _generate_from_template(product_name, description, style)


def generate_tags(
    product_name: str,
    category: str = "",
    target_audience: str = "",
    selling_points: str = "",
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> list[str]:
    """
    独立生成话题标签

    Args:
        product_name: 产品名称
        category: 产品类别
        target_audience: 目标人群
        selling_points: 核心卖点

    Returns:
        标签列表
    """
    system_prompt, user_prompt = get_tags_prompt(
        product_name=product_name,
        category=category,
        target_audience=target_audience,
        selling_points=selling_points,
    )

    try:
        text, _, _ = call_llm(
            system_prompt, user_prompt, api_key=api_key, provider=provider
        )
        _, tags = _extract_and_parse_tags(text)
        return tags
    except Exception as e:
        logger.warning("标签生成失败，使用默认标签: %s", e)
        return [
            f"#{product_name}",
            "#日常穿搭",
            "#配饰分享",
            "#好物记录",
        ]


# ============================================================
# 第二轮：方向扩写
# ============================================================

def generate_direction_content(
    product_name: str,
    description: str,
    price: str,
    selling_points: str,
    direction: dict,
    style: str = "种草推荐",
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> DirectionContentResult:
    """
    第二轮：根据方向生成 3 篇差异化文案

    Args:
        product_name: 产品名称
        description: 产品描述
        price: 产品价格
        selling_points: 核心卖点
        direction: 方向字典 (id, name, target_audience, angle, hook_type, style_hint)
        provider: 指定 LLM 提供商
        api_key: 直接指定 API Key

    Returns:
        DirectionContentResult
    """
    system_prompt, user_prompt = get_direction_content_prompt(
        product_name=product_name,
        description=description,
        price=price,
        selling_points=selling_points,
        direction=direction,
        style=style,
    )

    dir_id = direction.get("id", "?")
    dir_name = direction.get("name", "未知方向")

    try:
        text, provider_name, model_name = call_llm(
            system_prompt, user_prompt,
            api_key=api_key,
            provider=provider,
            temperature=0.95,  # 第二轮高温度增加变体多样性
        )
        raw = extract_json(text)
        posts_data = raw.get("posts", [])

        posts = []
        for i, p in enumerate(posts_data[:3]):
            tags = p.get("tags", [])
            if isinstance(tags, str):
                tags = [t for t in tags.split() if t.startswith("#")]
            tags = tags[:5]
            posts.append(DirectionPost(
                index=i + 1,
                direction_id=dir_id,
                direction_name=dir_name,
                hook_style=soften_ai_style(p.get("hook_style", "")),
                title=soften_story_title(p.get("title", "")),
                content=soften_ai_style(p.get("content", "")),
                tags=tags,
            ))

        if posts:
            return DirectionContentResult(
                direction_id=dir_id,
                direction_name=dir_name,
                posts=posts,
                provider=provider_name,
                model=model_name,
            )
        logger.warning("方向 %s LLM 返回帖子数量为 0，使用模板", dir_id)
    except Exception as e:
        logger.warning("方向 %s 文案生成失败，使用模板: %s", dir_id, e)

    # 兜底：模板生成
    posts = _generate_template_posts(product_name, description, direction)
    return DirectionContentResult(
        direction_id=dir_id,
        direction_name=dir_name,
        posts=posts,
        provider="template",
        model="template",
    )


# ============================================================
# 模板兜底（方向扩写）
# ============================================================

# 模板文本提取为模块级常量，避免每次调用重复构造
_TEMPLATE_POSTS_BY_STYLE = {
    "测评": {
        "content": [
            "我最近试这类配饰的时候，会先看它会不会把整套穿搭拖得太满。\n\n那天换上浅色上衣顺手戴了一下，{desc}。第一眼不算特别高调，但靠近镜子看会发现细节比远看顺，属于越看越稳的类型。\n\n我后来又配了件针织试了一次，感觉它对日常衣服挺友好，不需要为了它重新想一套。要说取舍，就是如果你本来就偏爱很强势的单品，它会显得安静一点。\n\n所以我的结论不是惊艳，而是耐留。\n\n#配饰测评 #穿搭细节 #日常记录",
            "前阵子帮人挑礼物的时候，我把类似的配饰看了不少，最后会记住这一条，是因为它没有那种很急着吸引人的感觉。\n\n{desc}。这种东西送人不算冒险，自留也不容易闲置，重点不是一下子多亮眼，而是搭起来不费劲。\n\n我自己比较在意的是它会不会挑衣服。试下来浅色衬衫、针织都能接住，但如果整身已经有很多设计，它反而不一定最合适。\n\n比较适合想要一点细节、但不想太满的人。\n\n#送礼参考 #配饰记录 #真实感受",
            "我现在看这类配饰，会先看近看的层次，再看它放到日常里会不会显得生硬。\n\n{desc}。它的细节不是那种远远就能看到的类型，反而要在自然光下慢一点看，才会觉得做工和线条还挺顺。\n\n这个优点也带来一个小限制，就是光线差的时候存在感会弱一点，所以更适合白天或者靠窗的位置。\n\n如果你也更在意细节而不是第一眼冲击，这种会比想象中更耐看。\n\n#材质细节 #配饰测评 #穿搭灵感",
        ],
        "titles": [
            "那天试戴了一下，意外挺顺",
            "挑礼物时记住了这一条",
            "这条要近看才有意思",
        ],
    },
    "教程": {
        "content": [
            "我后来发现这类配饰要戴得自然，第一步不是叠很多，而是先把衣服颜色收住。\n\n那天我把上衣换成浅一点的颜色，再戴上它，{desc}，画面一下就顺了很多。\n\n如果旁边已经有明显花纹或者其他亮点，它就容易被抢掉。所以我现在更习惯让它跟白色、米色、浅灰这类单品放在一起。\n\n不是多复杂的方法，但对日常搭配真的很省力。\n\n#配饰搭配 #穿搭思路 #日常分享",
            "拍这类配饰的时候，我现在反而不太会专门摆动作。\n\n更自然的方法是站到窗边，手里顺便拿个杯子、翻一下书或者整理袖口。{desc}，这样拍出来不会像在硬展示，反而像真的刚好记录到一个瞬间。\n\n如果光线太平，细节容易被吃掉，所以我一般会选侧光，画面会更有层次。\n\n这算是我最近比较常用的小办法。\n\n#拍照小技巧 #配饰分享 #真实记录",
            "如果想戴得不那么用力，我会先决定这一天只让一个细节当主角。\n\n{desc}。它本身已经有存在感的时候，旁边就别再加太多别的饰品，不然容易互相抢。\n\n我现在常用的做法是留它一个重点，其他地方尽量简一点。这样不是更高级，只是更耐看，也更像自己的日常。\n\n比起堆很多元素，这种方法更容易长期用下去。\n\n#穿搭方法 #配饰搭配 #日常灵感",
        ],
        "titles": [
            "最近戴这类配饰的一个小习惯",
            "这类照片我现在都这样拍",
            "想戴得自然一点，我会这样配",
        ],
    },
    "种草": {
        "content": [
            "那天出门前临时把衬衫换成了浅一点的颜色，手边刚好放着这个，就顺手戴上了。\n\n原本没想太多，结果走到窗边照了一下，{desc}，细节反而是在近看时才慢慢出来的。它不会一下把穿搭拉得很满，这点我还挺喜欢。\n\n后来那天出门一路都没再动它，说明它至少不会让人戴一会儿就想摘。真要挑一点，就是光线暗的时候存在感会弱一些。\n\n所以它给我的感觉不是惊艳，是顺手，而且有一点后劲。\n\n#日常穿搭 #配饰分享 #好物记录",
            "前阵子看礼物的时候，脑子里反复留下来的不是最亮眼的那种，反而是安静一点的。\n\n{desc}。它没有很重的年龄感，也不太挑场合，所以不管是送人还是自己留着，都不会显得太冒险。\n\n我后来想了一下，喜欢它其实不是因为它一下子多特别，而是它放在日常里很容易成立。浅色衣服、针织、衬衫都能接得住，省得为了一个配饰重新想整套。\n\n这种东西不一定惊艳，但比较容易留在手边。\n\n#送礼参考 #配饰记录 #日常好物",
            "我现在看这类配饰，会先看它在自然光下是什么感觉，而不是先看第一眼亮不亮。\n\n{desc}。有些东西远看很抢，但近看会空；它正好相反，是靠近一点才觉得层次慢慢出来。\n\n这也决定了它更适合干净一点的穿搭，尤其是白衬衫、浅针织或者偏新中式一点的衣服。偏运动或者风格很强的搭配，反而未必最适合它。\n\n如果你也更喜欢低调一点的质感，这种会更耐看。\n\n#材质细节 #穿搭灵感 #配饰观察",
        ],
        "titles": [
            "那天出门前，我顺手戴了这条",
            "挑礼物时反而记住了这一条",
            "这条不是第一眼，但越看越顺",
        ],
    },
}

_HOOK_STYLES = ["日常场景", "送礼/搭配", "细节观察"]


def _generate_template_posts(
    product_name: str,
    description: str,
    direction: dict,
    style: str = "种草推荐",
) -> list[DirectionPost]:
    """模板兜底生成 3 篇"""
    dir_id = direction.get("id", "?")
    dir_name = direction.get("name", "通用")
    style_key = _normalize_story_style(style)

    style_data = _TEMPLATE_POSTS_BY_STYLE.get(style_key, _TEMPLATE_POSTS_BY_STYLE["种草"])
    templates = style_data["content"]
    title_templates = style_data["titles"]

    posts = []
    for i, tpl in enumerate(templates):
        content = soften_ai_style(tpl.format(product=product_name, desc=description[:50]))
        posts.append(DirectionPost(
            index=i + 1,
            direction_id=dir_id,
            direction_name=dir_name,
            hook_style=_HOOK_STYLES[i],
            title=soften_story_title(title_templates[i]),
            content=content,
            tags=[f"#{product_name}", "#日常穿搭", "#配饰分享", f"#{dir_name}"],
        ))
    return posts
