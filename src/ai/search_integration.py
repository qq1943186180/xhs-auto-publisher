"""
搜索工具集成 - 生成前自动搜索相关资料
使用 Jina s.jina.ai 搜索端点（正确用法，参考 jina-ai/reader GitHub）
"""
import json
import logging
import urllib.request
import urllib.parse
import threading

from src.utils.logger import get_logger

logger = get_logger("search_integration")


def search_web(query: str, max_results: int = 5) -> list:
    """
    使用 Jina s.jina.ai 搜索相关资料
    返回: [{"title": ..., "content": ..., "url": ...}, ...]
    """
    if not query:
        return []

    results = []

    # 正确用法：s.jina.ai/<URL编码后的搜索关键词>
    # 参考：https://github.com/jina-ai/reader
    try:
        encoded = urllib.parse.quote(query)
        jina_url = f"https://s.jina.ai/{encoded}"

        req = urllib.request.Request(
            jina_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        # s.jina.ai 返回 JSON 格式：
        # { "query": "...", "results": [ { "title": "...", "url": "...", "content": "..." }, ... ] }
        if isinstance(data, dict) and "results" in data:
            raw_results = data["results"]
        elif isinstance(data, list):
            raw_results = data
        else:
            # 非 JSON 模式，按文本处理
            raw_results = []

        for item in raw_results[:max_results]:
            results.append({
                "title": item.get("title", "")[:80],
                "content": item.get("content", "")[:500],
                "url": item.get("url", ""),
            })

        if results:
            logger.info("Jina 搜索获取 %d 条结果", len(results))
            return results[:max_results]

    except Exception as e:
        logger.debug("Jina 搜索（JSON）失败，尝试文本模式: %s", e)

    # 降级：不用 Accept: application/json，直接读文本结果
    try:
        encoded = urllib.parse.quote(query)
        jina_url = f"https://s.jina.ai/{encoded}"

        req = urllib.request.Request(
            jina_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # 文本模式：按行解析，提取标题和内容
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        title = ""
        snippet = ""
        for line in lines:
            if line.startswith("# ") and not title:
                title = line[2:].strip()
            elif len(line) > 30 and not line.startswith("#") and not line.startswith(">") and not line.startswith("["):
                snippet = line
                break

        if title or snippet:
            results.append({
                "title": title or f"搜索：{query}",
                "content": snippet[:500],
                "url": "",
            })
            logger.info("Jina 搜索（文本模式）获取结果")
            return results

    except Exception as e:
        logger.debug("Jina 搜索（文本模式）也失败: %s", e)

    # 最终降级：直接基于 query 生成参考文本
    logger.info("搜索降级：直接使用关键词「%s」作为参考资料", query)
    return [{
        "title": f"主题：{query}",
        "content": f"请根据「{query}」这个主题，生成一篇有深度、有见解的小红书种草文案。可以从以下角度展开：背景介绍、核心特点、使用体验、搭配建议、购买推荐。",
        "url": ""
    }]


def format_search_results_for_prompt(results: list) -> str:
    """将搜索结果格式化为 prompt 文本"""
    if not results:
        return ""

    parts = ["\n\n# 参考资料（搜索结果）\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", f"资料 {i}")
        content = r.get("content", "")[:400]
        url = r.get("url", "")
        if content:
            parts.append(f"{i}. **{title}**：{content}")
            if url:
                parts.append(f"   来源：{url}")
        elif title:
            parts.append(f"{i}. **{title}**")

    return "\n".join(parts)


class SearchWorker(threading.Thread):
    """后台搜索线程"""

    def __init__(self, query: str, callback=None):
        super().__init__(daemon=True)
        self.query = query
        self.callback = callback
        self.results = []

    def run(self):
        try:
            self.results = search_web(self.query)
            if self.callback:
                # 在主线程回调
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.callback(self.results))
        except Exception as e:
            logger.error("Search worker failed: %s", e)
            if self.callback:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.callback([]))
