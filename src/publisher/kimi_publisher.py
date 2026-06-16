"""
小红书发布器 - Kimi WebBridge 浏览器自动化
"""
import json
import os
import time
import logging
import requests
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

KIMI_API = "http://127.0.0.1:10086/command"
XHS_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish"
SESSION_NAME = "xhs-publish"


def kimi(action: str, args: dict = None, timeout: int = 30) -> dict:
    payload = {"action": action, "args": args or {}, "session": SESSION_NAME}
    try:
        resp = requests.post(KIMI_API, json=payload, timeout=timeout)
        return resp.json()
    except Exception as e:
        logger.error(f"Kimi error: {e}")
        return {"ok": False, "error": {"message": str(e)}}


def _ok(r: dict) -> bool:
    return r.get("ok", False) or r.get("data", {}).get("success", False)


def _val(r: dict):
    """Get value from evaluate result"""
    return r.get("data", {}).get("value", None)


def js_eval(code: str, timeout: int = 15):
    """Execute JS expression, return value"""
    r = kimi("evaluate", {"code": code}, timeout=timeout)
    if _ok(r):
        return _val(r)
    logger.warning(f"JS eval failed: {r}")
    return None


def navigate(url: str) -> bool:
    r = kimi("navigate", {"url": url})
    return _ok(r)


def click(selector: str) -> bool:
    r = kimi("click", {"selector": selector})
    return _ok(r)


def fill(selector: str, value: str) -> bool:
    r = kimi("fill", {"selector": selector, "value": value})
    return _ok(r)


def upload(selector: str, files: list) -> bool:
    r = kimi("upload", {"selector": selector, "files": files})
    return _ok(r)


def screenshot(path: str = None):
    args = {"format": "png"}
    if path:
        args["path"] = path
    r = kimi("screenshot", args)
    return r


def check_kimi_health() -> bool:
    try:
        resp = requests.get("http://127.0.0.1:10086/status", timeout=5)
        data = resp.json()
        return data.get("running") and data.get("extension_connected")
    except:
        return False


@dataclass
class PublishNote:
    title: str
    content: str
    images: list = field(default_factory=list)
    tags: str = ""


@dataclass
class PublishResult:
    success: bool
    title: str
    message: str = ""
    note_url: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


def publish_note(note: PublishNote) -> PublishResult:
    """Publish a note to XHS via Kimi WebBridge"""
    logger.info(f"开始发布: {note.title[:30]}")

    # 1. Navigate
    if not navigate(XHS_PUBLISH_URL):
        return PublishResult(False, note.title, "导航失败")
    time.sleep(4)

    # 2. Click "上传图片" tab (3rd .creator-tab)
    logger.info("切换到上传图片...")
    click(".creator-tab:nth-child(3)")
    time.sleep(2)

    # 3. Upload images
    if note.images:
        logger.info(f"上传 {len(note.images)} 张图片...")
        ok = upload('input[type="file"]', note.images)
        if not ok:
            return PublishResult(False, note.title, "图片上传失败")
        logger.info("图片已上传，等待处理...")
        time.sleep(10)  # Wait for upload + processing

    # 4. Check what appeared after upload
    page_state = js_eval("""
    (() => {
        const inputs = document.querySelectorAll('input, textarea, [contenteditable]');
        const r = [];
        inputs.forEach((el, i) => r.push(i + ':' + el.tagName + '|' + el.type + '|' + (el.placeholder||'').substring(0,20)));
        return r.join(', ');
    })()
    """)
    logger.info(f"Page state after upload: {page_state}")

    # 5. Fill title
    logger.info("填写标题...")
    title_selectors = [
        'input[placeholder*="标题"]',
        '#title-input',
        'input[class*="title"]',
        'input[maxlength="20"]',
    ]
    title_ok = False
    for sel in title_selectors:
        if fill(sel, note.title):
            title_ok = True
            logger.info(f"标题已填 ({sel})")
            break

    if not title_ok:
        # Try contenteditable for title
        title_result = js_eval("""
        (() => {
            const els = document.querySelectorAll('[contenteditable]');
            if (els.length > 0) {
                els[0].focus();
                els[0].innerHTML = '""" + note.title.replace("'", "\\'") + """';
                els[0].dispatchEvent(new Event('input', {bubbles: true}));
                return 'ok';
            }
            return 'not found';
        })()
        """)
        logger.info(f"Title via JS: {title_result}")

    time.sleep(1)

    # 6. Fill content
    logger.info("填写正文...")
    content_text = note.content
    if note.tags:
        content_text += "\n\n" + note.tags

    content_selectors = [
        '[contenteditable="true"]',
        '.ql-editor',
        '#post-textarea',
    ]
    content_ok = False
    for sel in content_selectors:
        if fill(sel, content_text):
            content_ok = True
            logger.info(f"正文已填 ({sel})")
            break

    if not content_ok:
        escaped = content_text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        content_result = js_eval("""
        (() => {
            const els = document.querySelectorAll('[contenteditable]');
            // Skip first one (title), fill second one (content)
            for (let i = 0; i < els.length; i++) {
                if (els[i].textContent.length < 50) {
                    els[i].focus();
                    els[i].innerHTML = '""" + escaped + """';
                    els[i].dispatchEvent(new Event('input', {bubbles: true}));
                    return 'ok: ' + i;
                }
            }
            return 'not found: ' + els.length;
        })()
        """)
        logger.info(f"Content via JS: {content_result}")

    time.sleep(2)

    # 7. Screenshot
    screenshot()

    # 8. Click publish
    logger.info("点击发布...")
    pub_selectors = [
        'button:has-text("发布")',
        'button[class*="submit"]',
        'button[class*="publish"]',
    ]
    pub_ok = False
    for sel in pub_selectors:
        if click(sel):
            pub_ok = True
            break

    if not pub_ok:
        js_eval("""
        (() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '发布' || btn.textContent.trim() === '发布笔记') {
                    btn.click();
                    return 'ok';
                }
            }
            return 'not found';
        })()
        """)

    time.sleep(5)
    screenshot()
    logger.info("发布流程完成")
    return PublishResult(True, note.title, "已提交发布")
