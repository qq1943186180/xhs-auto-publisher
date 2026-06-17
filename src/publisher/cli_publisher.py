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
    selectors = [
        'button:has-text("图文")',
        '.creator-tab:has-text("图文")',
        '.creator-tab:has-text("上传图文")',
        ".creator-tab:nth-child(3)",
    ]
    _, tab = await _first_visible(page, selectors)
    if tab:
        await tab.click(timeout=3000)
        await page.wait_for_timeout(1500)
        return

    await page.evaluate("""
        () => {
            const tabs = document.querySelectorAll('button, .creator-tab, [role="tab"]');
            const imgTab = Array.from(tabs).find(t => /图文|图片/.test(t.textContent || ''));
            if (imgTab) imgTab.click();
        }
    """)
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
        await title_input.fill(title)
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
        '[contenteditable="true"]',
        ".ql-editor",
        "#post-textarea",
        'textarea[placeholder*="正文"]',
        'textarea[placeholder*="内容"]',
    ]
    _, content_input = await _first_visible(page, selectors)
    if content_input:
        await content_input.click()
        await content_input.evaluate("""
            (el, text) => {
                if ('value' in el) {
                    el.value = text;
                } else {
                    el.innerText = text;
                }
                el.dispatchEvent(new Event('input', {bubbles: true}));
            }
        """, text)
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
    selectors = [
        'button:has-text("发布")',
        'button:has-text("发布笔记")',
        'button[class*="publish"]',
        'button[class*="submit"]',
    ]
    _, button = await _first_visible(page, selectors)
    clicked = False
    if button:
        await button.click(timeout=3000)
        clicked = True
    else:
        clicked = await page.evaluate("""
            () => {
                const buttons = document.querySelectorAll('button');
                for (const button of buttons) {
                    if (/^发布$|发布笔记/.test((button.textContent || '').trim())) {
                        button.click();
                        return true;
                    }
                }
                return false;
            }
        """)

    if not clicked:
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

            if auto_publish:
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
