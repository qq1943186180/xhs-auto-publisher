"""
统一 AI 味道清洗模块
合并 content_generator._soften_ai_style 和 title_generator._TITLE_REPLACEMENTS，
按优先级分层处理标题和正文的 AI 营销味道。
"""

import re

# ============================================================
# 标题专用替换（更严格，去除夸张词 + emoji）
# ============================================================

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

# ============================================================
# 正文专用替换（保留更多表达，但去除明显营销味）
# ============================================================

_CONTENT_REPLACEMENTS = {
    "姐妹们！！！": "",
    "姐妹们": "",
    "家人们": "",
    "救命": "",
    "真的绝了": "还挺耐看",
    "绝绝子": "比较耐看",
    "绝了": "不错",
    "闭眼入": "可以先看看",
    "冲就对了": "按自己的风格选",
    "冲冲冲": "按需入",
    "天花板": "比较稳定",
    "被问爆": "有人问",
    "后悔没早买": "最近才注意到",
    "谁用谁知道": "实际看个人习惯",
    "智商税": "不太适合所有人",
    "必须给你们安利": "想简单记录一下",
    "太值了": "还算合适",
    "性价比超高": "价格和质感还算匹配",
    "颜值在线": "外观比较顺眼",
    "品质过硬": "做工还可以",
    "总结一下": "",
    "总之": "",
    "整体来说": "",
    "评论区问我": "有问题可以问我",
    "有喜欢的姐妹": "如果你也在看这类",
    "高级感满满": "看起来比较干净",
    "氛围感拉满": "氛围比较自然",
}


def soften_title(title: str) -> str:
    """清洗标题中的 AI 营销味道（严格模式）"""
    for old, new in _TITLE_REPLACEMENTS.items():
        title = title.replace(old, new)
    # 去除所有 emoji
    title = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", title)
    # 多个感叹号替换为句号
    title = re.sub(r"[!！]{2,}", "。", title)
    # 去除竖线分隔符
    title = re.sub(r"\s*[｜|]\s*", " ", title)
    # 合并多余空格
    title = re.sub(r"\s{2,}", " ", title)
    # 去除首尾杂字符
    title = title.strip(" -｜|。")
    return title


def soften_ai_style(text: str) -> str:
    """清洗正文中的 AI 营销味道（正文模式，保留自然表达）"""
    for old, new in _CONTENT_REPLACEMENTS.items():
        text = text.replace(old, new)
    # 多个感叹号替换为句号
    text = re.sub(r"[!！]{2,}", "。", text)
    # 多个波浪号合并
    text = re.sub(r"[~～]{2,}", "～", text)
    # 移除总结类过渡词
    text = re.sub(r"(总结一下[:：]?|总之[:：]?|整体来说[:：]?)", "", text)
    # 保留最多 1 个 emoji，其余移除
    emoji_pattern = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    seen = 0

    def keep_one(match):
        nonlocal seen
        seen += 1
        return match.group(0) if seen == 1 else ""

    text = emoji_pattern.sub(keep_one, text)
    # 合并过多空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def soften_story_title(text: str) -> str:
    """清洗故事型标题（基于正文清洗 + 去除 emoji）"""
    text = soften_ai_style(text)
    # 再次确保无 emoji
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
    text = re.sub(r"\s*[｜|]\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" -｜|。")
