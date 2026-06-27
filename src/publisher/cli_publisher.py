"""Command line publisher used by the GUI and manual tests."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("xhs-cli")

BROWSER_DATA = Path.home() / ".xhs-publisher" / "browser-data"
CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish"


def _read_text_arg(value: str | None, file_path: str | None, label: str) -> str:
    if value and file_path:
        raise ValueError(f"{label} can only be provided once")
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    if value:
        return value
    raise ValueError(f"missing {label}")


async def _first_visible(page, selectors: list[str], timeout: int = 3000):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0 and await locator.is_visible(timeout=timeout):
                return selector, locator
        except Exception:
            continue
    return None, None


async def _wait_for_login(page, headless: bool, timeout_sec: int = 120) -> dict | None:
    current_url = page.url.lower()
    if "login" not in current_url and "customer" not in current_url:
        return None

    if headless:
        return {"success": False, "message": "not logged in; run once with a visible browser"}

    logger.warning("Login required. Please scan the QR code in the browser window.")
    for _ in range(timeout_sec):
        await page.wait_for_timeout(1000)
        if "login" not in page.url.lower() and "customer" not in page.url.lower():
            logger.info("Login detected.")
            return None
    return {"success": False, "message": "login timeout"}


async def _switch_to_image_tab(page) -> None:
    # 先检查是否已经在笔记编辑页（已有图片上传区域），如果是则跳过 tab 切换
    already_editor = await page.evaluate("""
        () => {
            // 笔记编辑页有 contenteditable 正文区域和标题输入框
            const editor = document.querySelector('div[contenteditable="true"]');
            const titleInput = document.querySelector('input[placeholder*="标题"], input[class*="title"]');
            return !!(editor && titleInput);
        }
    """)
    if already_editor:
        logger.info("Already on note editor page, skipping tab switch.")
        return

    # 策略1: JS 精确点击可见的"上传图文"tab
    clicked = await page.evaluate("""
        () => {
            const all = document.querySelectorAll('.creator-tab, [role="tab"], button, span, div, li, a');
            for (const tab of all) {
                const text = (tab.textContent || '').trim();
                const rect = tab.getBoundingClientRect();
                if ((text === '上传图文' || text === '图文') && rect.width > 0 && rect.height > 0
                    && rect.left >= 0 && rect.top >= 0
                    && getComputedStyle(tab).display !== 'none'
                    && getComputedStyle(tab).visibility !== 'hidden') {
                    tab.click();
                    return true;
                }
            }
            return false;
        }
    """)
    if clicked:
        await page.wait_for_timeout(2000)
        return

    # 策略2: Playwright locator 组合选择器
    selectors = [
        '.creator-tab:has-text("上传图文") >> visible=true',
        'button:has-text("上传图文") >> visible=true',
        'span:has-text("上传图文") >> visible=true',
        'div[role="tab"]:has-text("图文") >> visible=true',
        'button:has-text("图文") >> visible=true',
        'a:has-text("图文") >> visible=true',
        'li:has-text("图文") >> visible=true',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                await loc.click(timeout=3000)
                await page.wait_for_timeout(2000)
                return
        except Exception:
            continue

    logger.warning("Could not find or click '上传图文' tab, proceeding anyway.")
    await page.wait_for_timeout(1500)


async def _upload_images(page, images: list[str]) -> dict | None:
    if not images:
        return None

    valid_images = [str(Path(img).resolve()) for img in images if Path(img).exists()]
    if not valid_images:
        return {"success": False, "message": "no valid image files"}

    file_input = page.locator('input[type="file"]').first
    if await file_input.count() == 0:
        return {"success": False, "message": "file input not found"}

    await file_input.set_input_files(valid_images)
    logger.info("Uploaded %s image(s), waiting for preview.", len(valid_images))
    for _ in range(30):
        has_preview = await page.evaluate("""
            () => {
                const selectors = [
                    '.el-upload-list__item',
                    'img[src^="blob:"]',
                    '.upload-preview',
                    '.note-image-item',
                    '[class*="preview"] img'
                ];
                return selectors.some(sel => {
                    return Array.from(document.querySelectorAll(sel)).some(el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    });
                });
            }
        """)
        if has_preview:
            return None
        await page.wait_for_timeout(1000)
    return {"success": False, "message": "image upload was not confirmed"}


async def _fill_title(page, title: str) -> dict | None:
    selectors = [
        'input[placeholder*="标题"]',
        "#title-input",
        'input[class*="title"]',
        'input[maxlength="20"]',
    ]
    _, title_input = await _first_visible(page, selectors)
    if title_input:
        await title_input.click()
        await page.wait_for_timeout(300)
        # 先清空
        await title_input.press("Control+a")
        await title_input.press("Backspace")
        await page.wait_for_timeout(200)
        # 逐字输入，触发 Vue 框架的 keydown/input 事件
        await title_input.type(title, delay=80)
        await page.wait_for_timeout(500)
        return None

    ok = await page.evaluate("""
        (title) => {
            const inputs = document.querySelectorAll('input');
            for (const input of inputs) {
                const hint = `${input.placeholder || ''} ${input.className || ''}`;
                if (/标题|title/i.test(hint)) {
                    input.focus();
                    input.value = title;
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
            }
            return false;
        }
    """, title)
    return None if ok else {"success": False, "message": "title input not found"}


async def _fill_content(page, content: str, tags: str = "") -> dict | None:
    text = f"{content}\n\n{tags}".strip() if tags else content
    selectors = [
        '.tiptap.ProseMirror',
        'div[contenteditable="true"]',
        ".ql-editor",
        "#post-textarea",
        'textarea[placeholder*="正文"]',
        'textarea[placeholder*="内容"]',
    ]
    _, content_input = await _first_visible(page, selectors)
    if content_input:
        await content_input.click()
        await page.wait_for_timeout(500)
        # 清空已有内容
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(300)
        # 逐行输入（模拟真人）
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.strip():
                await page.keyboard.type(line.strip(), delay=50)
            if i < len(lines) - 1:
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(100)
        await page.wait_for_timeout(500)
        return None

    ok = await page.evaluate("""
        (text) => {
            const editors = document.querySelectorAll('[contenteditable], textarea');
            for (const el of editors) {
                if ((el.textContent || el.value || '').length < 50) {
                    el.focus();
                    if ('value' in el) {
                        el.value = text;
                    } else {
                        el.innerText = text;
                    }
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    return true;
                }
            }
            return false;
        }
    """, text)
    return None if ok else {"success": False, "message": "content editor not found"}


async def _dismiss_overlays(page) -> None:
    """关闭可能遮挡底部按钮的下拉面板（智能标题、话题建议等）。"""
    # 策略1: 点击标题输入框（安全区域），让焦点从正文编辑器移走
    try:
        title_sel = 'input[placeholder*="标题"], input[class*="title"], input[maxlength="20"]'
        title_loc = page.locator(title_sel).first
        if await title_loc.count() > 0 and await title_loc.is_visible(timeout=1000):
            await title_loc.click()
            await page.wait_for_timeout(300)
    except Exception:
        pass
    # 按 Escape 关闭可能的弹出层
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)
    # 点击页面左上角空白区域确保下拉关闭
    await page.mouse.click(100, 50)
    await page.wait_for_timeout(500)
    # JS fallback: 派发 mousedown 到 body
    await page.evaluate("""
        () => {
            const evt = new MouseEvent('mousedown', {bubbles: true, clientX: 100, clientY: 50});
            document.body.dispatchEvent(evt);
            document.body.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, clientX: 100, clientY: 50}));
        }
    """)
    await page.wait_for_timeout(300)


async def _click_save_draft(page) -> dict | None:
    """点击「暂存离开」将笔记保存到草稿箱，而不是公开发布。"""
    # ── 第 0 步：关闭可能遮挡按钮的下拉面板 ─────────────
    await _dismiss_overlays(page)

    # ── 第 1 步：滚动到底部，让操作栏可见 ───────────────
    await page.evaluate("""
        () => {
            window.scrollTo(0, document.body.scrollHeight);
            const containers = document.querySelectorAll(
                '[class*="content"], [class*="editor"], [class*="publish"], [class*="container"], [class*="scroll"]'
            );
            containers.forEach(c => { c.scrollTop = c.scrollHeight; });
        }
    """)
    await page.keyboard.press("End")
    await page.wait_for_timeout(500)

    # 滚动后可能又弹出下拉，再关一次
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    try:
        title_loc = page.locator('input[placeholder*="标题"], input[class*="title"]').first
        if await title_loc.count() > 0 and await title_loc.is_visible(timeout=1000):
            await title_loc.click()
            await page.wait_for_timeout(300)
    except Exception:
        pass
    await page.mouse.click(100, 50)
    await page.wait_for_timeout(500)

    # 策略1: 先找"发布"按钮，再在同级找"暂存离开"
    clicked = await page.evaluate("""
        () => {
            // 先找"发布"按钮的位置
            const all = document.querySelectorAll('button, div, span, a, p, li');
            let publishBtn = null;
            for (const el of all) {
                const text = (el.textContent || '').trim();
                if (text === '发布') {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 20 && rect.height > 20) {
                        publishBtn = el;
                        break;
                    }
                }
            }
            if (!publishBtn) return null;

            // 在发布按钮的父级容器里找"暂存离开"
            let parent = publishBtn.parentElement;
            for (let depth = 0; depth < 6 && parent; depth++) {
                const siblings = parent.querySelectorAll('button, div, span, a, p');
                for (const sib of siblings) {
                    if (sib === publishBtn) continue;
                    const text = (sib.textContent || '').trim();
                    const rect = sib.getBoundingClientRect();
                    if (rect.width < 10 || rect.height < 10) continue;
                    if (text.includes('暂存') || text.includes('存草稿') || text.includes('草稿')) {
                        sib.click();
                        return text;
                    }
                }
                parent = parent.parentElement;
            }
            return null;
        }
    """)
    if clicked:
        logger.info("Clicked draft button (near publish): %s", clicked)
        # 跳过后续策略
    else:
        # 策略2: 直接全局搜索包含"暂存"的元素
        clicked = await page.evaluate("""
            () => {
                const all = document.querySelectorAll('button, div, span, a, p, li');
                // 优先精确匹配
                const keywords = ['暂存离开', '存草稿', '保存草稿', '暂存', '存为草稿'];
                for (const el of all) {
                    const text = (el.textContent || '').trim();
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 10 || rect.height < 10) continue;
                    if (rect.width > 300) continue;
                    if (rect.left < 0 || rect.top < 0) continue;
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    if (keywords.includes(text)) {
                        el.click();
                        return text;
                    }
                }
                // 模糊匹配
                for (const el of all) {
                    const text = (el.textContent || '').trim();
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 10 || rect.height < 10) continue;
                    if (rect.width > 300) continue;
                    if (rect.left < 0 || rect.top < 0) continue;
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    if (text.includes('暂存') || text.includes('存草稿')) {
                        el.click();
                        return text;
                    }
                }
                return null;
            }
        """)
        if clicked:
            logger.info("Clicked draft button (global search): %s", clicked)

    if not clicked:
        # 策略3: Playwright locator (shadow DOM 穿透 + force click)
        draft_selectors = [
            'button:has-text("暂存离开")',
            'button:has-text("存草稿")',
            'button:has-text("暂存")',
            'span:has-text("暂存离开")',
            'div:has-text("暂存离开")',
            'xhs-publish-btn >> button:has-text("暂存")',
            'xhs-publish-btn >> button:has-text("存草稿")',
            'xhs-publish-btn >> :text("暂存离开")',
            'xhs-publish-btn >> :text("暂存")',
        ]
        for sel in draft_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    # 尝试普通点击，失败则 force click
                    try:
                        await loc.click(timeout=2000)
                    except Exception:
                        await loc.click(force=True)
                    clicked = sel
                    logger.info("Clicked draft button via selector: %s", sel)
                    break
            except Exception:
                continue

    if not clicked:
        # 策略4: 搜索 shadow DOM (xhs-publish-btn 自定义元素)
        shadow_clicked = await page.evaluate("""
            () => {
                // 递归搜索 shadow DOM
                function searchShadow(root, keywords) {
                    if (!root) return null;
                    const els = root.querySelectorAll('button, div, span, a');
                    for (const el of els) {
                        const text = (el.textContent || '').trim();
                        for (const kw of keywords) {
                            if (text.includes(kw)) {
                                const rect = el.getBoundingClientRect();
                                if (rect.width > 5 && rect.height > 5) {
                                    el.click();
                                    return text;
                                }
                            }
                        }
                        // 递归子 shadow DOM
                        if (el.shadowRoot) {
                            const found = searchShadow(el.shadowRoot, keywords);
                            if (found) return found;
                        }
                    }
                    return null;
                }
                const keywords = ['暂存离开', '暂存', '存草稿', '保存草稿'];
                // 搜索所有有 shadow root 的元素
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    if (el.shadowRoot) {
                        const found = searchShadow(el.shadowRoot, keywords);
                        if (found) return found;
                    }
                }
                return null;
            }
        """)
        if shadow_clicked:
            clicked = shadow_clicked
            logger.info("Clicked draft button via shadow DOM: %s", shadow_clicked)

    if not clicked:
        # 策略5: 在 xhs-publish-btn 的 sticky 位置附近点击
        # 诊断显示该元素在 x=280, y=810, w=680, h=90
        sticky_rect = await page.evaluate("""
            () => {
                const el = document.querySelector('xhs-publish-btn');
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {x: Math.round(rect.left), y: Math.round(rect.top), w: Math.round(rect.width), h: Math.round(rect.height)};
            }
        """)
        if sticky_rect and sticky_rect['w'] > 50:
            # 在该元素区域内点击（左侧通常是"暂存离开"，右侧是"发布"）
            # 暂存离开一般在左侧 1/3 区域
            click_x = sticky_rect['x'] + sticky_rect['w'] * 0.2
            click_y = sticky_rect['y'] + sticky_rect['h'] * 0.5
            logger.info("Trying coordinate click at (%s, %s) in xhs-publish-btn", click_x, click_y)
            await page.mouse.click(click_x, click_y)
            clicked = f"coordinate({click_x:.0f},{click_y:.0f})"
            await page.wait_for_timeout(1000)
            # 检查是否真的触发了什么
            post_click = await page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button, .el-button, .modal button');
                    for (const btn of btns) {
                        const text = (btn.textContent || '').trim();
                        if (text === '确认' || text === '确定' || text === '保存' || text === '存草稿' || text === '确认离开') {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                btn.click();
                                return text;
                            }
                        }
                    }
                    return null;
                }
            """)
            if post_click:
                logger.info("Confirmed after coordinate click: %s", post_click)

    if not clicked:
        # 截图用于调试
        try:
            await page.screenshot(path=str(BROWSER_DATA / "draft_button_not_found.png"))
        except Exception:
            pass
        # 调试：dump 所有可见的按钮和短文本元素（包括 shadow DOM）
        debug_info = await page.evaluate("""
            () => {
                const results = [];
                // 搜索 light DOM
                const all = document.querySelectorAll('button, div, span, a, p');
                for (const el of all) {
                    const text = (el.textContent || '').trim();
                    if (!text || text.length > 20) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 10 || rect.height < 10) continue;
                    if (rect.left < 0 || rect.top < 0) continue;
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    results.push({t: text, tag: el.tagName, y: Math.round(rect.top), x: Math.round(rect.left), w: Math.round(rect.width), src: 'light'});
                }
                // 搜索 shadow DOM
                function searchShadow(root, label) {
                    if (!root) return;
                    const els = root.querySelectorAll('button, div, span, a, p');
                    for (const el of els) {
                        const text = (el.textContent || '').trim();
                        if (!text || text.length > 20) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.width < 5 || rect.height < 5) continue;
                        results.push({t: text, tag: el.tagName, y: Math.round(rect.top), x: Math.round(rect.left), w: Math.round(rect.width), src: label});
                    }
                }
                const customEls = document.querySelectorAll('xhs-publish-btn, [class*="publish-btn"], [class*="footer"], [class*="action-bar"]');
                for (const el of customEls) {
                    if (el.shadowRoot) searchShadow(el.shadowRoot, 'shadow:' + el.tagName);
                }
                return results.slice(-60);
            }
        """)
        logger.error("Draft button not found. Visible elements: %s", debug_info)
        return {"success": False, "message": "未找到草稿保存按钮（暂存离开）", "debug": debug_info}

    # 等待可能出现的确认对话框并自动确认
    await page.wait_for_timeout(1500)
    confirmed = await page.evaluate("""
        () => {
            // 处理"确认离开"或"是否保存草稿"弹窗
            const btns = document.querySelectorAll('button, .el-button, .modal button');
            for (const btn of btns) {
                const text = (btn.textContent || '').trim();
                if (text === '确认' || text === '确定' || text === '保存'
                    || text === '存草稿' || text === '确认离开') {
                    const rect = btn.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        btn.click();
                        return text;
                    }
                }
            }
            return null;
        }
    """)
    if confirmed:
        logger.info("Confirmed draft dialog: %s", confirmed)

    await page.wait_for_timeout(2000)
    return None


async def _wait_for_publish_result(page, initial_url: str, timeout_sec: int = 30) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if page.url != initial_url and "publish" not in page.url.lower():
            return True, "publish redirect detected"

        signal = await page.evaluate("""
            () => {
                const nodes = document.querySelectorAll(
                    '.toast, .notification, .message, [class*="toast"], [class*="message"], [class*="error"], [class*="success"]'
                );
                for (const node of nodes) {
                    const text = (node.textContent || '').trim();
                    if (!text) continue;
                    if (/成功|已发布|发布成功|提交成功|success/i.test(text)) {
                        return {ok: true, text};
                    }
                    if (/失败|错误|异常|违规|请上传|不能为空|error|failed/i.test(text)) {
                        return {ok: false, text};
                    }
                }
                return null;
            }
        """)
        if signal:
            return bool(signal.get("ok")), signal.get("text") or "publish status detected"
        await page.wait_for_timeout(1000)
    return False, "publish result was not confirmed"


async def _click_publish(page) -> dict | None:
    initial_url = page.url

    # 优先用 JS 精确点击（XHS 用 div 而非 button）
    clicked = await page.evaluate("""
        () => {
            // 策略1: 找精确文本"发布"的可见按钮/div
            const all = document.querySelectorAll('button, div, span');
            for (const el of all) {
                const text = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (text === '发布' && rect.width > 20 && rect.height > 20
                    && rect.left >= 0 && rect.top >= 0
                    && getComputedStyle(el).display !== 'none') {
                    el.click();
                    return true;
                }
            }
            // 策略2: 找 class 含 publishBtn / btn-publish 的元素
            const btns = document.querySelectorAll('[class*="publishBtn"], [class*="btn-publish"], .btn-wrapper');
            for (const el of btns) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 20 && rect.height > 20) {
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """)
    if clicked:
        pass
    else:
        selectors = [
            'button:has-text("发布")',
            'button:has-text("发布笔记")',
            'button[class*="publish"]',
            'button[class*="submit"]',
            'div.btn-wrapper',
            '[class*="publishBtn"]',
        ]
        _, button = await _first_visible(page, selectors)
        if button:
            await button.click(timeout=3000)
        else:
            return {"success": False, "message": "publish button not found"}

    ok, message = await _wait_for_publish_result(page, initial_url)
    if not ok:
        return {"success": False, "message": message, "url": page.url}
    return None


async def publish_note(
    title: str,
    content: str,
    images: list[str] | None = None,
    tags: str = "",
    auto_publish: bool = False,
    headless: bool = False,
    draft: bool = False,
) -> dict:
    """
    发布笔记：优先用 xiaohongshu-creator CLI（CDP直连Edge，最可靠），
    失败时降级到 Playwright 自动化。
    draft=True 时保存到草稿箱而不是公开发布。
    """
    # ── 方式1：xiaohongshu-creator CLI（推荐）──────────────
    if not draft:
        cli_result = _publish_via_cli(title, content, images, tags)
        if cli_result is not None:
            return cli_result

    # ── 方式2：Playwright 自动化（降级方案 / 草稿模式）────
    logger.info("CLI 发布不可用%s，降级到 Playwright 自动化", "（草稿模式）" if draft else "")
    return await _publish_via_playwright(title, content, images, tags, headless, draft=draft)


def _ensure_edge_cdp(port: int = 9222) -> bool:
    """确保 Edge 带 CDP 端口运行。如果没运行则启动。"""
    import socket

    def _port_open():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(("127.0.0.1", port))
                return True
        except (ConnectionRefusedError, TimeoutError, OSError):
            return False

    def _is_edge_cdp():
        """验证 CDP 端口确实是 Edge（不是别的进程）"""
        try:
            import urllib.request
            req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3)
            data = json.loads(req.read().decode("utf-8"))
            return "Edg/" in data.get("Browser", "")
        except Exception:
            return False

    # 端口已开且是 Edge CDP → 直接返回
    if _port_open() and _is_edge_cdp():
        return True

    # 端口已开但不是 Edge（可能是 Chrome）→ 不抢占
    if _port_open() and not _is_edge_cdp():
        logger.warning("端口 %d 被非 Edge 浏览器占用", port)
        return False

    # 找 Edge 可执行文件
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_exe = None
    for p in edge_paths:
        if os.path.isfile(p):
            edge_exe = p
            break
    if not edge_exe:
        logger.warning("未找到 Edge 可执行文件")
        return False

    # Edge 可能在跑但没开 CDP → 先关掉再重启
    try:
        subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"],
                       capture_output=True, timeout=10)
        time.sleep(2)
    except Exception:
        pass

    # 启动 Edge 带 CDP
    try:
        subprocess.Popen(
            [edge_exe, f"--remote-debugging-port={port}", "--remote-allow-origins=*"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # 等端口就绪，最多 15 秒
        for _ in range(15):
            time.sleep(1)
            if _port_open() and _is_edge_cdp():
                logger.info("Edge CDP 已就绪 (port=%d)", port)
                return True
    except Exception as exc:
        logger.error("启动 Edge 失败: %s", exc)

    return False


def _publish_via_cli(
    title: str,
    content: str,
    images: list[str] | None = None,
    tags: str = "",
) -> dict | None:
    """用 xiaohongshu-creator CLI 发布（CDP 直连 Edge/Chrome）"""
    import subprocess as _sp

    # 确保 Edge 带 CDP 端口运行
    if not _ensure_edge_cdp():
        logger.warning("Edge CDP 端口未就绪，CLI 可能会启动 Chrome")

    cli_dir = Path.home() / "workspace" / "skills" / "xiaohongshu-creator"
    cli_py = cli_dir / "scripts" / "cli.py"
    venv_py = cli_dir / ".venv" / "Scripts" / "python.exe"
    if not cli_py.exists():
        logger.debug("CLI 不存在: %s", cli_py)
        return None

    python_exe = str(venv_py) if venv_py.exists() else sys.executable

    # 写临时文件
    tmp_dir = Path.home() / ".xhs-publisher" / "_cli_publish_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    title_file = tmp_dir / "title.txt"
    content_file = tmp_dir / "content.txt"
    full_content = f"{content}\n\n{tags}".strip() if tags else content
    title_file.write_text(title, encoding="utf-8")
    content_file.write_text(full_content, encoding="utf-8")

    # 收集图片路径
    image_paths = []
    for img in (images or []):
        p = Path(img)
        if p.exists():
            image_paths.append(str(p.resolve()))
    if not image_paths:
        logger.warning("CLI 发布: 没有有效图片")
        return None

    cmd = [
        python_exe, str(cli_py), "publish",
        "--title-file", str(title_file),
        "--content-file", str(content_file),
        "--images", *image_paths,
    ]

    logger.info("调用 CLI 发布: %s 张图片", len(image_paths))
    try:
        result = _sp.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(cli_dir), encoding="utf-8", errors="replace",
        )
        stdout = result.stdout.strip()

        # 解析 JSON 输出（最后一个完整 JSON 对象）
        parsed = None
        # 找最后一个 { 开始的完整 JSON
        last_brace = stdout.rfind("{")
        if last_brace >= 0:
            # 从最后一个 { 开始尝试解析
            for end in range(len(stdout), last_brace, -1):
                try:
                    parsed = json.loads(stdout[last_brace:end])
                    break
                except json.JSONDecodeError:
                    continue
        # fallback: 逐行找 JSON
        if not parsed:
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        parsed = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

        if parsed and parsed.get("success"):
            logger.info("CLI 发布成功: %s", parsed.get("status", ""))
            return {
                "success": True,
                "message": f"发布成功（CLI）: {parsed.get('status', '')}",
                "image_count": len(image_paths),
            }
        else:
            error_msg = (parsed or {}).get("error") or stdout[-300:]
            logger.warning("CLI 发布失败: %s", error_msg)
            return {
                "success": False,
                "message": f"CLI 发布失败: {error_msg}",
            }
    except _sp.TimeoutExpired:
        logger.error("CLI 发布超时")
        return {"success": False, "message": "CLI 发布超时（120s）"}
    except Exception as exc:
        logger.error("CLI 执行异常: %s", exc)
        return None  # 返回 None 让调用方降级到 Playwright


async def _publish_via_playwright(
    title: str,
    content: str,
    images: list[str] | None = None,
    tags: str = "",
    headless: bool = False,
    draft: bool = False,
) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"success": False, "message": "playwright is not installed"}

    BROWSER_DATA.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(CREATOR_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            login_error = await _wait_for_login(page, headless=headless)
            if login_error:
                return login_error

            await _switch_to_image_tab(page)

            for step in (
                await _upload_images(page, images or []),
                await _fill_title(page, title),
                await _fill_content(page, content, tags),
            ):
                if step:
                    return step

            pre_publish = str(BROWSER_DATA / "pre_publish.png")
            try:
                await page.screenshot(path=pre_publish)
            except Exception:
                logger.debug("pre-publish screenshot failed", exc_info=True)

            if draft:
                # 草稿模式：点击"暂存离开"保存到草稿箱
                draft_error = await _click_save_draft(page)
                if draft_error:
                    return draft_error
                return {
                    "success": True,
                    "message": "已保存到草稿箱",
                    "url": page.url,
                    "draft": True,
                }
            elif auto_publish:
                publish_error = await _click_publish(page)
                if publish_error:
                    return publish_error
            else:
                logger.info("Content is filled. Confirm publish in the browser, then press Enter.")
                input("Press Enter after publishing...")

            final_screenshot = str(BROWSER_DATA / "post_publish.png")
            try:
                await page.screenshot(path=final_screenshot)
            except Exception:
                logger.debug("post-publish screenshot failed", exc_info=True)

            return {
                "success": True,
                "message": "publish completed",
                "url": page.url,
                "screenshot": final_screenshot,
            }
        except Exception as exc:
            logger.error("publish failed: %s", exc)
            try:
                await page.screenshot(path=str(BROWSER_DATA / "error.png"))
            except Exception:
                logger.debug("error screenshot failed", exc_info=True)
            return {"success": False, "message": str(exc)}
        finally:
            await context.close()


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["publish"]:
        argv = argv[1:]

    parser = argparse.ArgumentParser(description="XHS CLI publisher")
    parser.add_argument("--title", help="note title")
    parser.add_argument("--title-file", help="read title from a UTF-8 text file")
    parser.add_argument("--content", help="note content")
    parser.add_argument("--content-file", help="read content from a UTF-8 text file")
    parser.add_argument("--images", nargs="*", default=[], help="image paths")
    parser.add_argument("--tags", default="", help="topic tags, e.g. '#tag1 #tag2'")
    parser.add_argument("--auto", action="store_true", help="click publish automatically")
    parser.add_argument("--draft", action="store_true", help="save to drafts instead of publishing publicly")
    parser.add_argument("--headless", action="store_true", help="run browser headless")
    parser.add_argument("--json", action="store_true", help="print a JSON result")
    args = parser.parse_args(argv)

    try:
        title = _read_text_arg(args.title, args.title_file, "title")
        content = _read_text_arg(args.content, args.content_file, "content")
    except ValueError as exc:
        parser.error(str(exc))

    result = asyncio.run(
        publish_note(
            title=title,
            content=content,
            images=args.images,
            tags=args.tags,
            auto_publish=args.auto,
            headless=args.headless,
            draft=args.draft,
        )
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    elif result.get("success"):
        logger.info("%s", result.get("message", "success"))
    else:
        logger.error("%s", result.get("message", "failed"))

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
