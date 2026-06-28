"""
URL 内容提取模块
方案1：Jina Reader API (r.jina.ai) 读取网页
方案2：直接抓取网页 HTML
方案3：从 URL path 解码标题（适合 MSN / 今日头条等 JS 渲染页）
方案4：降级 - 返回失败，让用户手动输入

代理配置（按优先级）：
  1. 环境变量 XHS_PROXY / HTTPS_PROXY / HTTP_PROXY
  2. config_manager xhs.proxy 字段
超时配置：config_manager xhs.timeout（默认 15s）
"""
import os
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
    # 纯品牌名（JS 渲染页静态 HTML 常见）
    "msn", "weibo", "bilibili", "baidu", "zhihu",
    "xiaohongshu", "toutiao", "douyin", "taobao", "tmall",
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


def _get_proxy() -> str:
    """读取代理配置（环境变量优先，其次 config_manager）"""
    # 1. 环境变量（与 llm_client 保持一致）
    proxy = (
        os.environ.get("XHS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    if proxy:
        return proxy
    # 2. config_manager
    try:
        from src.config.config_manager import get_config_manager
        return get_config_manager().get("xhs.proxy", "") or ""
    except Exception:
        return ""


def _get_timeout() -> float:
    """读取超时配置（config_manager xhs.timeout，默认 15s）"""
    try:
        from src.config.config_manager import get_config_manager
        t = get_config_manager().get("xhs.timeout", 15)
        return float(t) if t else 15.0
    except Exception:
        return 15.0


def _make_opener(proxy: str) -> urllib.request.OpenerDirector:
    """创建带代理（或明确禁用系统代理）的 opener"""
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    else:
        # 空字典 = 禁用系统代理，避免意外使用系统级代理
        handler = urllib.request.ProxyHandler({})
    return urllib.request.build_opener(handler)


def extract_url_content(url: str) -> dict:
    """
    提取 URL 内容
    返回: {"topic": ..., "summary": ..., "content": ...}
    提取失败返回空 dict {}
    """
    if not url:
        return {}

    url = url.strip()
    # 处理用户误粘贴两个 URL 拼在一起的情况（取第一个）
    second_http = url.find("http", 4)
    if second_http != -1:
        url = url[:second_http].rstrip("?&")

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

    # 方案3：从 URL path 解码（适合 MSN / 今日头条等 JS 渲染页）
    path_topic = _extract_from_url_path(url)
    if path_topic and _is_valid_topic(path_topic):
        logger.info("URL路径提取成功: %s", path_topic)
        return {"topic": path_topic, "title": path_topic, "summary": "", "content": ""}

    # 方案4：提取失败，返回空（让UI提示手动输入）
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
    if not re.search(r"[一-鿿 a-zA-Z0-9]", topic):
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


def _extract_from_url_path(url: str) -> str:
    """
    从 URL path 解码标题。
    适合 MSN / 今日头条 / 腾讯新闻等 JS 渲染页面，
    这类页面把文章标题直接编码进 URL path。
    """
    try:
        parsed = urllib.parse.urlparse(url)
        segments = [s for s in parsed.path.strip("/").split("/") if s]
        # 去掉纯 ID 段，如 ar-AA266obs、article/12345678、p/abcdef
        meaningful = [
            s for s in segments
            if not re.match(r'^(ar|p|article|post|item|news|video|A|id)-?[A-Za-z0-9]{4,}$', s, re.IGNORECASE)
            and not re.match(r'^\d{6,}$', s)
        ]
        if not meaningful:
            return ""
        last = meaningful[-1]
        # 去掉文件扩展名
        last = re.sub(r'\.(html?|php|aspx?|jsp).*$', '', last, flags=re.IGNORECASE)
        # percent 解码
        last = urllib.parse.unquote(last)
        # 连字符/下划线 → 空格（URL slug 转可读标题）
        last = re.sub(r'[-_]+', ' ', last)
        last = re.sub(r'\s+', ' ', last).strip()
        if len(last) >= 5:
            return last[:80]
    except Exception:
        pass
    return ""


def _fetch_jina(url: str) -> dict:
    """用 Jina Reader API 抓取网页（支持代理）"""
    proxy = _get_proxy()
    timeout = _get_timeout()
    try:
        api_url = f"https://r.jina.ai/{url}"
        req = urllib.request.Request(api_url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/plain",
        })
        opener = _make_opener(proxy)
        with opener.open(req, timeout=timeout) as resp:
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
    """直接抓取网页内容（支持代理）"""
    proxy = _get_proxy()
    timeout = _get_timeout()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        opener = _make_opener(proxy)
        with opener.open(req, timeout=timeout) as resp:
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
