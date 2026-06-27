"""
热点主题获取模块
从知乎/微博/百度热榜免费抓取热点，无需 API Key
"""
import logging
import urllib.request
import urllib.parse
import json
import re

from src.utils.logger import get_logger

logger = get_logger("ai.hot_topics")


def fetch_hot_topics(source: str = "全部") -> list:
    """
    获取热点主题列表
    返回: [{"title": ..., "description": ..., "source": ..., "rank": ...}, ...]
    """
    results = []

    if source in ("全部", "知乎"):
        results.extend(_fetch_zhihu())

    if source in ("全部", "微博"):
        results.extend(_fetch_weibo())

    if source in ("全部", "百度"):
        results.extend(_fetch_baidu())

    return results[:50]  # 最多返回 50 条


def _fetch_zhihu() -> list:
    """从知乎热榜获取热点"""
    try:
        url = "https://www.zhihu.com/hot"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # 尝试解析 JSON 数据
        json_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.+?});', content)
        if json_match:
            data = json.loads(json_match.group(1))
            hot_list = data.get("hotList", [])
            return [
                {
                    "title": item.get("target", {}).get("title", ""),
                    "description": item.get("target", {}).get("excerpt", ""),
                    "source": "知乎",
                    "rank": i + 1,
                }
                for i, item in enumerate(hot_list[:20])
            ]

        # 降级：从 HTML 提取
        titles = re.findall(r'<div[^>]*class="[^"]*HotItem[^"]*"[^>]*>\s*<div[^>]*>\s*<div[^>]*>([^<]+)</div>', content)
        return [
            {"title": t.strip(), "description": "", "source": "知乎", "rank": i + 1}
            for i, t in enumerate(titles[:20])
        ]

    except Exception as e:
        logger.warning("知乎热榜获取失败: %s", e)
        return []


def _fetch_weibo() -> list:
    """从微博热搜获取热点"""
    try:
        url = "https://s.weibo.com/top/summary"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # 简单提取：查找热点标题
        titles = re.findall(r'<a[^>]+href="[^"]*realtime\?[^"]*"[^>]*>([^<]+)</a>', content)
        if not titles:
            titles = re.findall(r'<span[^>]*class="[^"]*txt[^"]*"[^>]*>([^<]+)</span>', content)

        return [
            {"title": t.strip(), "description": "", "source": "微博", "rank": i + 1}
            for i, t in enumerate(titles[:20])
        ]

    except Exception as e:
        logger.warning("微博热搜获取失败: %s", e)
        return []


def _fetch_baidu() -> list:
    """从百度热搜获取热点"""
    try:
        url = "https://top.baidu.com/board?tab=realtime"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # 尝试解析 JSON
        json_match = re.search(r'window\.__INITIAL_DATA__\s*=\s*({.+?})\s*;', content)
        if json_match:
            data = json.loads(json_match.group(1))
            cards = data.get("cards", [])
            results = []
            for card in cards[:1]:  # 只取第一个卡片
                for item in card.get("content", [])[:20]:
                    results.append({
                        "title": item.get("word", ""),
                        "description": item.get("desc", ""),
                        "source": "百度",
                        "rank": item.get("index", 0),
                    })
            return results

        # 降级：从 HTML 提取
        titles = re.findall(r'"word"\s*:\s*"([^"]+)"', content)
        return [
            {"title": t.strip(), "description": "", "source": "百度", "rank": i + 1}
            for i, t in enumerate(titles[:20])
        ]

    except Exception as e:
        logger.warning("百度热搜获取失败: %s", e)
        return []
