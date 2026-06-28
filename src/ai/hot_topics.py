"""
热点主题获取模块
从微博/百度热榜免费抓取热点，无需 API Key
三路并行请求，单路超时不影响整体
"""
import urllib.request
import urllib.parse
import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from src.utils.logger import get_logger

logger = get_logger("ai.hot_topics")

_TIMEOUT = 6  # 单路请求超时（秒）
_HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def fetch_hot_topics(source: str = "全部") -> list:
    """
    并行获取热点主题列表
    返回: [{"title": ..., "description": ..., "source": ..., "rank": ...}, ...]
    """
    tasks = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        if source in ("全部", "微博"):
            tasks["微博"] = pool.submit(_fetch_weibo)
        if source in ("全部", "百度"):
            tasks["百度"] = pool.submit(_fetch_baidu)
        # 知乎需要登录 Cookie，仅在明确选择时才请求
        if source == "知乎":
            tasks["知乎"] = pool.submit(_fetch_zhihu)

        results = []
        for name, future in tasks.items():
            try:
                items = future.result(timeout=_TIMEOUT + 3)
                results.extend(items)
                logger.info("%s 热点: %d 条", name, len(items))
            except TimeoutError:
                logger.warning("%s 热点请求超时，已跳过", name)
                future.cancel()
            except Exception as e:
                logger.warning("%s 热点获取失败: %s", name, e)

    # 按来源分组排序：微博 → 百度 → 知乎
    order = {"微博": 0, "百度": 1, "知乎": 2}
    results.sort(key=lambda x: (order.get(x.get("source", ""), 9), x.get("rank", 99)))
    return results[:60]


def _fetch_weibo() -> list:
    """微博热搜（Ajax JSON API，无需登录）"""
    url = "https://weibo.com/ajax/side/hotSearch"
    req = urllib.request.Request(url, headers={
        **_HEADERS_BROWSER,
        "Accept": "application/json",
        "Referer": "https://weibo.com/",
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    items = data.get("data", {}).get("realtime", [])
    results = []
    for i, item in enumerate(items[:25]):
        word = item.get("word", "").strip()
        if not word:
            continue
        # 过滤广告词条
        if item.get("is_ad") or "广告" in item.get("flag_desc", ""):
            continue
        results.append({
            "title": word,
            "description": item.get("note", ""),
            "source": "微博",
            "rank": i + 1,
        })
    return results


def _fetch_baidu() -> list:
    """百度实时热搜"""
    url = "https://top.baidu.com/board?tab=realtime"
    req = urllib.request.Request(url, headers={
        **_HEADERS_BROWSER,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://www.baidu.com/",
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        content = resp.read().decode("utf-8", errors="ignore")

    # 优先 JSON 解析
    m = re.search(r'"content"\s*:\s*(\[.+?\])\s*,\s*"side"', content, re.DOTALL)
    if m:
        try:
            items = json.loads(m.group(1))
            return [
                {
                    "title": it.get("word", "").strip(),
                    "description": it.get("desc", ""),
                    "source": "百度",
                    "rank": i + 1,
                }
                for i, it in enumerate(items[:25])
                if it.get("word", "").strip()
            ]
        except Exception:
            pass

    # 降级：正则提取 word 字段（去重）
    titles = list(dict.fromkeys(re.findall(r'"word"\s*:\s*"([^"]+)"', content)))
    return [
        {"title": t.strip(), "description": "", "source": "百度", "rank": i + 1}
        for i, t in enumerate(titles[:25])
        if t.strip()
    ]


def _fetch_zhihu() -> list:
    """知乎热榜（需要登录 Cookie，未登录返回空列表）"""
    try:
        url = "https://www.zhihu.com/hot"
        req = urllib.request.Request(url, headers={
            **_HEADERS_BROWSER,
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\});\s*\n', content, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            hot_list = data.get("hotList", [])
            return [
                {
                    "title": item.get("target", {}).get("title", "").strip(),
                    "description": item.get("target", {}).get("excerpt", ""),
                    "source": "知乎",
                    "rank": i + 1,
                }
                for i, item in enumerate(hot_list[:20])
                if item.get("target", {}).get("title", "").strip()
            ]
    except Exception as e:
        logger.debug("知乎热榜: %s（通常需要登录Cookie）", e)
    return []
