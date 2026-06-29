"""
搜索工具集成 - 多后端：Tavily / Serper.dev / Jina / DuckDuckGo
优先使用已配置的 API Key，降级免费接口
"""
import json
import os
import urllib.request
import urllib.parse
import threading

from src.utils.logger import get_logger

logger = get_logger("search_integration")


def _get_proxy() -> str:
    proxy = (
        os.environ.get("XHS_PROXY") or
        os.environ.get("HTTPS_PROXY") or
        os.environ.get("HTTP_PROXY") or
        ""
    )
    if not proxy:
        try:
            from src.config.config_manager import get_config_manager
            proxy = get_config_manager().get("xhs.proxy", "") or ""
        except Exception:
            pass
    return proxy.strip()


def _get_timeout() -> int:
    try:
        from src.config.config_manager import get_config_manager
        t = get_config_manager().get("xhs.timeout", 15)
        return int(t) if t else 15
    except Exception:
        return 15


def _make_opener(proxy: str):
    handler = urllib.request.ProxyHandler(
        {"http": proxy, "https": proxy} if proxy else {}
    )
    return urllib.request.build_opener(handler)


def _get_tavily_key() -> str:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        try:
            from src.config.config_manager import get_config_manager
            key = get_config_manager().get("search.tavily_key", "") or ""
        except Exception:
            pass
    return key.strip()


def _search_tavily(query: str, max_results: int, proxy: str, timeout: int) -> list:
    """Tavily AI 搜索（需 API Key，免费 1000 次/月，专为 AI 应用设计）"""
    api_key = _get_tavily_key()
    if not api_key:
        raise ValueError("未配置 TAVILY_API_KEY")

    payload = json.dumps({
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
    }).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = _make_opener(proxy)
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())

    results = []
    for item in data.get("results", [])[:max_results]:
        results.append({
            "title": item.get("title", "")[:80],
            "content": item.get("content", "")[:500],
            "url": item.get("url", ""),
        })
    if not results:
        raise ValueError("Tavily 返回空结果")
    return results


def _get_serper_key() -> str:
    key = os.environ.get("SERPER_API_KEY", "")
    if not key:
        try:
            from src.config.config_manager import get_config_manager
            key = get_config_manager().get("search.serper_key", "") or ""
        except Exception:
            pass
    return key.strip()


def _search_serper(query: str, max_results: int, proxy: str, timeout: int) -> list:
    """Serper.dev Google 搜索（需 API Key，免费 2500 次/月）"""
    api_key = _get_serper_key()
    if not api_key:
        raise ValueError("未配置 SERPER_API_KEY")

    payload = json.dumps({
        "q": query,
        "num": max_results,
        "gl": "cn",
        "hl": "zh-cn",
    }).encode()
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=payload,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    opener = _make_opener(proxy)
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())

    results = []
    for item in data.get("organic", [])[:max_results]:
        results.append({
            "title": item.get("title", "")[:80],
            "content": item.get("snippet", "")[:500],
            "url": item.get("link", ""),
        })
    if not results:
        raise ValueError("Serper 返回空结果")
    return results


def _search_jina(query: str, max_results: int, proxy: str, timeout: int) -> list:
    """Jina Reader 搜索（s.jina.ai，无需 Key，国内需代理）"""
    encoded = urllib.parse.quote(query)
    req = urllib.request.Request(
        f"https://s.jina.ai/{encoded}",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        },
    )
    opener = _make_opener(proxy)
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))

    raw = data.get("results", data if isinstance(data, list) else [])
    results = []
    for item in raw[:max_results]:
        if isinstance(item, dict):
            results.append({
                "title": item.get("title", "")[:80],
                "content": item.get("content", "")[:500],
                "url": item.get("url", ""),
            })
    if not results:
        raise ValueError("Jina 返回空结果")
    return results


def _search_duckduckgo(query: str, max_results: int, proxy: str, timeout: int) -> list:
    """DuckDuckGo 即时答案 API（无需 Key）"""
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    })
    req = urllib.request.Request(
        f"https://api.duckduckgo.com/?{params}",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    opener = _make_opener(proxy)
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))

    results = []
    if data.get("AbstractText"):
        results.append({
            "title": data.get("Heading", query)[:80],
            "content": data["AbstractText"][:500],
            "url": data.get("AbstractURL", ""),
        })
    for topic in data.get("RelatedTopics", [])[:max_results]:
        if isinstance(topic, dict) and topic.get("Text"):
            results.append({
                "title": topic.get("Text", "")[:80],
                "content": topic.get("Text", "")[:500],
                "url": topic.get("FirstURL", ""),
            })
        if len(results) >= max_results:
            break
    if not results:
        raise ValueError("DuckDuckGo 返回空结果")
    return results[:max_results]


def search_web(query: str, max_results: int = 5) -> list:
    """
    多后端搜索，按优先级依次尝试：
    1. Tavily（配置 TAVILY_API_KEY 时，AI 友好，免费 1000 次/月）
    2. Serper.dev（配置 SERPER_API_KEY 时，谷歌结果质量最佳）
    3. Jina s.jina.ai（有代理效果好，无代理也尝试）
    4. DuckDuckGo 即时答案（免费，无需 Key）
    5. 关键词提示（兜底）
    """
    if not query:
        return []

    proxy = _get_proxy()
    timeout = min(_get_timeout(), 20)

    # 1. Tavily（AI 搜索，免费 1000 次/月）
    if _get_tavily_key():
        try:
            results = _search_tavily(query, max_results, proxy, timeout)
            logger.info("Tavily 搜索成功: %d 条", len(results))
            return results
        except Exception as e:
            logger.warning("Tavily 搜索失败: %s", e)

    # 2. Serper（谷歌质量，需 key）
    if _get_serper_key():
        try:
            results = _search_serper(query, max_results, proxy, timeout)
            logger.info("Serper 搜索成功: %d 条", len(results))
            return results
        except Exception as e:
            logger.warning("Serper 搜索失败: %s", e)

    # 3. Jina（有代理效果好，无代理也试一次）
    try:
        results = _search_jina(query, max_results, proxy, timeout)
        logger.info("Jina 搜索成功: %d 条", len(results))
        return results
    except Exception as e:
        logger.debug("Jina 搜索失败: %s", e)

    # 4. DuckDuckGo（免费兜底）
    try:
        results = _search_duckduckgo(query, max_results, proxy, timeout)
        logger.info("DuckDuckGo 搜索成功: %d 条", len(results))
        return results
    except Exception as e:
        logger.debug("DuckDuckGo 搜索失败: %s", e)

    # 5. 关键词兜底
    logger.info("搜索降级为关键词提示：「%s」", query)
    return [{
        "title": f"主题：{query}",
        "content": (
            f"请根据「{query}」这个主题，生成一篇有深度的小红书种草文案。"
            "可从以下角度展开：背景介绍、核心特点、使用体验、搭配建议、购买推荐。"
        ),
        "url": "",
    }]


def format_search_results_for_prompt(results: list) -> str:
    if not results:
        return ""
    parts = ["# 参考资料（搜索结果）\n"]
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
    """后台搜索线程，完成后通过 QTimer 在主线程回调"""

    def __init__(self, query: str, callback=None):
        super().__init__(daemon=True)
        self.query = query
        self.callback = callback
        self.results = []
        self.error = None

    def run(self):
        try:
            self.results = search_web(self.query)
        except Exception as e:
            logger.error("SearchWorker failed: %s", e)
            self.error = str(e)
            self.results = []

        if self.callback:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.callback(self.results, self.error))
