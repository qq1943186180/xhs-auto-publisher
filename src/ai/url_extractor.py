"""
URL 内容提取模块
方案1：Jina Reader API (r.jina.ai) 读取网页
方案2：直接抓取网页 HTML
方案3：降级 - 返回失败，让用户手动输入
"""
import logging
import urllib.request
import urllib.parse
import re
import html as html_module

from src.utils.logger import get_logger

logger = get_logger("ai.url_extractor")

# 垃圾标题黑名单：这些词不能作为主题
_BAD_TOPICS = {
    "question", "explore", "index", "home", "search", "login",
    "error", "403", "404", "access denied", "参数错误",
    "www", "com", "cn", "org", "net", "html", "php",
}

# 网站域名映射
_DOMAIN_NAMES = {
    "zhihu": "知乎",
    "xiaohongshu": "小红书",
    "weibo": "微博",
    "baidu": "百度",
    "mp.weixin": "微信公众号",
    "bilibili": "B站",
    "douyin": "抖音",
    "taobao": "淘宝",
    "jd.com": "京东",
    "tmall": "天猫",
}


def extract_url_content(url: str) -> dict:
    """
    提取 URL 内容
    返回: {"topic": ..., "summary": ..., "content": ...}
    提取失败返回空 dict {}
    """
    if not url:
        return {}

    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    logger.info("开始提取 URL: %s", url)

    # 方案1：Jina Reader API
    result = _fetch_jina(url)
    if result and _is_valid_topic(result.get("topic", "")):
        logger.info("Jina 提取成功: %s", result.get("topic"))
        return result

    # 方案2：直接抓取网页
    result = _fetch_direct(url)
    if result and _is_valid_topic(result.get("topic", "")):
        logger.info("直接抓取提取成功: %s", result.get("topic"))
        return result

    # 方案3：提取失败，返回空（让UI提示手动输入）
    logger.warning("URL 提取失败，所有方案均未获得有效主题")
    return {}


def _is_valid_topic(topic: str) -> bool:
    """检查提取的主题是否有效"""
    if not topic or len(topic.strip()) < 3:
        return False
    topic_lower = topic.lower().strip()
    # 黑名单检查
    if topic_lower in _BAD_TOPICS:
        return False
    # 纯标点符号
    if not re.search(r"[\u4e00-\u9fff a-zA-Z0-9]", topic):
        return False
    # 太短或只是域名片段
    if len(topic_lower) < 3:
        return False
    return True


def _clean_title(t: str) -> str:
    """清理标题：去网站后缀、HTML实体、多余空白"""
    if not t:
        return ""
    # 解码 HTML 实体
    t = html_module.unescape(t)
    # 去多余空白
    t = re.sub(r"\s+", " ", t).strip()
    # 去常见网站后缀
    t = re.sub(r"\s*[-|·|_–—]\s*MSN.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[-|·|_–—]\s*新浪.*$", "", t)
    t = re.sub(r"\s*[-|·|_–—]\s*知乎.*$", "", t)
    t = re.sub(r"\s*[-|·|_–—]\s*小红书.*$", "", t)
    t = re.sub(r"\s*[-|·|_–—]\s*微博.*$", "", t)
    t = re.sub(r"\s*[-|·|_–—]\s*百度.*$", "", t)
    t = re.sub(r"\s*[-|·|_–—]\s*哔哩哔哩.*$", "", t)
    t = re.sub(r"\s*[-|·|_–—]\s*B站.*$", "", t)
    # 去尾部 | 分隔的副标题
    t = re.sub(r"\s*\|.*$", "", t).strip()
    return t


def _extract_best_title(content: str) -> str:
    """从网页内容中提取最佳标题（og:title 优先）"""
    candidates = []

    # 优先1：og:title meta 标签（property在前）
    og_match = re.search(
        r'<meta[^>]+(?:property|name)\s*=\s*["\'](?:og:)?title["\'][^>]*content\s*=\s*["\'](.*?)["\']',
        content, re.IGNORECASE | re.DOTALL
    )
    if not og_match:
        og_match = re.search(
            r'<meta[^>]+content\s*=\s*["\'](.*?)["\'][^>]*(?:property|name)\s*=\s*["\'](?:og:)?title["\']',
            content, re.IGNORECASE | re.DOTALL
        )
    if og_match:
        t = _clean_title(og_match.group(1))
        if len(t) >= 3:
            candidates.append(t)

    # 优先2：HTML <title> 标签
    title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if title_match:
        t = _clean_title(title_match.group(1))
        if len(t) >= 3:
            candidates.append(t)

    # 优先3：markdown # 标题（Jina 格式）
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            t = _clean_title(line.lstrip("#").strip())
            if len(t) >= 3:
                candidates.append(t)
                break

    # 优先4：h1 标签
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.IGNORECASE | re.DOTALL)
    if h1_match:
        t = _clean_title(re.sub(r"<[^>]+>", "", h1_match.group(1)))
        if len(t) >= 3:
            candidates.append(t)

    if candidates:
        return candidates[0][:80]
    return ""


def _extract_summary(content: str) -> str:
    """从内容中提取摘要"""
    # 如果是 markdown（Jina），找第一个有意义的段落
    for line in content.splitlines():
        line = line.strip()
        if (line and len(line) > 20
                and not line.startswith("#")
                and not line.startswith(">")
                and not line.startswith("[")
                and not line.startswith("|")
                and not line.startswith("Title:")
                and not line.startswith("URL Source:")
                and not line.startswith("Markdown Content:")):
            return line[:500]

    # 如果是 HTML，去标签后取纯文本
    text = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 20:
        return text[:500]
    return ""


def _fetch_jina(url: str) -> dict:
    """用 Jina Reader API 抓取网页"""
    try:
        api_url = f"https://r.jina.ai/{url}"
        req = urllib.request.Request(api_url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/plain",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        topic = _extract_best_title(content)
        summary = _extract_summary(content)

        if topic:
            return {
                "topic": topic,
                "title": topic,
                "summary": summary or topic,
                "content": content[:3000],
            }
    except Exception as e:
        logger.debug("Jina 抓取失败: %s", e)
    return {}


def _fetch_direct(url: str) -> dict:
    """直接抓取网页内容"""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            content_bytes = resp.read()
            # 尝试检测编码
            encoding = "utf-8"
            content_type = resp.headers.get("Content-Type", "")
            if "charset=" in content_type:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            try:
                content = content_bytes.decode(encoding)
            except Exception:
                content = content_bytes.decode("utf-8", errors="ignore")

        topic = _extract_best_title(content)
        summary = _extract_summary(content)

        if topic:
            return {
                "topic": topic,
                "title": topic,
                "summary": summary or topic,
                "content": content[:2000],
            }
    except Exception as e:
        logger.debug("直接抓取失败: %s", e)
    return {}
