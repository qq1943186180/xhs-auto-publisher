"""
小红书 CLI 发布工具
CDP 直连 Edge/Chrome，自动上传图片、填标题正文、点发布

用法:
    python cli.py publish --title "标题" --content "正文" --images img1.jpg img2.jpg
    python cli.py publish --title-file title.txt --content-file content.txt --images img1.jpg
    python cli.py login  (登录并保存登录态)
"""
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

# Paths
DATA_DIR = Path.home() / ".xhs-publisher"
BROWSER_DATA = DATA_DIR / "browser-data"
CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish"
HOME_URL = "https://creator.xiaohongshu.com/new/home"


def _find_browser_debug_port():
    """Try to find a running Chrome/Edge with remote debugging port"""
    import subprocess
    # Check common ports
    for port in [9222, 9223, 9224]:
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            data = json.loads(resp.read())
            return port, data.get("webSocketDebuggerUrl", "")
        except:
            continue
    return None, None


async def _launch_browser_with_cdp(headless=False):
    """Launch browser with CDP for direct control"""
    from playwright.async_api import async_playwright

    BROWSER_DATA.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()

    # Try to connect to existing browser first
    port, ws_url = _find_browser_debug_port()
    if ws_url:
        logger.info(f"连接已有浏览器 (port {port})...")
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            return pw, browser, context, page, True  # connected=True
        except Exception as e:
            logger.warning(f"连接失败: {e}，启动新浏览器")

    # Launch new persistent browser
    logger.info("启动新浏览器...")
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(BROWSER_DATA),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        args=[
            "--disable-blink-features=AutomationControlled",
        ],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    return pw, None, context, page, False


async def _ensure_logged_in(page, timeout_sec=120):
    """Check if logged in, wait for manual login if needed"""
    current_url = page.url
    if "login" in current_url.lower() or "customer" in current_url.lower():
        logger.warning("需要登录！请在浏览器窗口中扫码登录")
        for i in range(timeout_sec):
            await page.wait_for_timeout(1000)
            if "login" not in page.url.lower():
                logger.info("登录成功！")
                return True
        return False
    return True


async def cmd_login():
    """Login and save session"""
    pw, browser, context, page, connected = await _launch_browser_with_cdp(headless=False)
    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        if await _ensure_logged_in(page):
            print(json.dumps({"success": True, "message": "登录成功"}))
        else:
            print(json.dumps({"success": False, "message": "登录超时"}))
    finally:
        if browser and not connected:
            await browser.close()
        await pw.stop()


async def cmd_publish(title: str, content: str, images: list[str], tags: str = "", auto: bool = False):
    """Publish a note"""
    pw, browser, context, page, connected = await _launch_browser_with_cdp(headless=False)

    try:
        # 1. Navigate to publish page
        logger.info("导航到发布页...")
        await page.goto(CREATOR_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Check login
        if not await _ensure_logged_in(page):
            return {"success": False, "message": "未登录"}

        # 2. Switch to "上传图片" tab
        logger.info("切换到图文...")
        await page.wait_for_selector(".creator-tab", timeout=10000)
        tab_clicked = False
        for sel in [
            ".creator-tab:has-text('图文')",
            ".creator-tab:has-text('上传图文')",
            ".creator-tab:nth-child(3)",
        ]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    tab_clicked = True
                    break
            except:
                continue

        if not tab_clicked:
            await page.evaluate("""
                () => {
                    const tabs = document.querySelectorAll('.creator-tab');
                    const t = Array.from(tabs).find(x => /图文|图片/.test(x.textContent));
                    if (t) t.click();
                }
            """)
        await page.wait_for_timeout(2000)

        # 3. Upload images
        if images:
            valid = [img for img in images if os.path.exists(img)]
            if not valid:
                return {"success": False, "message": "图片不存在"}

            logger.info(f"上传 {len(valid)} 张图片...")
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(valid)
            await page.wait_for_timeout(8000)

            # Wait for upload complete
            for _ in range(30):
                has = await page.evaluate("""
                    () => {
                        const sels = ['.el-upload-list__item', 'img[src^="blob:"]', '.note-image-item'];
                        for (let s of sels) {
                            for (let el of document.querySelectorAll(s)) {
                                if (el.getBoundingClientRect().width > 0) return true;
                            }
                        }
                        return false;
                    }
                """)
                if has:
                    logger.info("图片上传完成")
                    break
                await page.wait_for_timeout(1000)

        # 4. Fill title
        logger.info("填写标题...")
        title_ok = False
        for sel in ['input[placeholder*="标题"]', 'input.d-text', 'input[class*="title"]']:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.fill(title)
                    title_ok = True
                    break
            except:
                continue

        if not title_ok:
            await page.evaluate("""
                (t) => {
                    for (const inp of document.querySelectorAll('input')) {
                        if ((inp.placeholder||'').includes('标题')) {
                            inp.value = t;
                            inp.dispatchEvent(new Event('input', {bubbles:true}));
                            return;
                        }
                    }
                }
            """, title)
        await page.wait_for_timeout(1000)

        # 5. Fill content
        logger.info("填写正文...")
        full = content
        if tags:
            full += "\n\n" + tags

        content_ok = False
        for sel in ['[contenteditable="true"]', '.ql-editor']:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click()
                    await page.wait_for_timeout(300)
                    await loc.evaluate("""
                        (el, text) => {
                            el.innerHTML = text.replace(/\\n/g, '<br>');
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        }
                    """, full)
                    content_ok = True
                    break
            except:
                continue

        if not content_ok:
            await page.evaluate("""
                (text) => {
                    for (const el of document.querySelectorAll('[contenteditable]')) {
                        if (el.textContent.length < 50) {
                            el.focus();
                            el.innerHTML = text.replace(/\\n/g, '<br>');
                            el.dispatchEvent(new Event('input', {bubbles:true}));
                            return;
                        }
                    }
                }
            """, full)
        await page.wait_for_timeout(2000)

        # 6. Take screenshot
        ss_path = str(BROWSER_DATA / "pre_publish.png")
        try:
            await page.screenshot(path=ss_path)
        except:
            pass

        # 7. Click publish
        if auto:
            logger.info("点击发布...")
            for sel in ['button:has-text("发布")', 'button[class*="publish"]']:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click(timeout=3000)
                        break
                except:
                    continue
            await page.wait_for_timeout(5000)
        else:
            logger.info("内容已填写，请在浏览器中手动确认发布")
            # Wait up to 5 minutes for user
            for _ in range(300):
                await page.wait_for_timeout(1000)
                url = page.url
                if "success" in url.lower() or CREATOR_URL not in url:
                    break

        return {
            "success": True,
            "message": "发布完成",
            "url": page.url,
            "screenshot": ss_path,
        }

    except Exception as e:
        logger.error(f"发布失败: {e}")
        return {"success": False, "message": str(e)}

    finally:
        if not connected:
            await context.close()
        await pw.stop()


def main():
    parser = argparse.ArgumentParser(description="小红书 CLI 发布工具")
    sub = parser.add_subparsers(dest="command")

    # Login
    sub.add_parser("login", help="登录小红书")

    # Publish
    pub = sub.add_parser("publish", help="发布笔记")
    pub.add_argument("--title", default="", help="标题")
    pub.add_argument("--content", default="", help="正文")
    pub.add_argument("--title-file", help="标题文件")
    pub.add_argument("--content-file", help="正文文件")
    pub.add_argument("--images", nargs="*", default=[], help="图片路径")
    pub.add_argument("--tags", default="", help="话题标签")
    pub.add_argument("--auto", action="store_true", help="自动发布")
    pub.add_argument("--headless", action="store_true")

    args = parser.parse_args()

    if args.command == "login":
        asyncio.run(cmd_login())
    elif args.command == "publish":
        title = args.title
        content = args.content
        if args.title_file:
            title = Path(args.title_file).read_text(encoding="utf-8").strip()
        if args.content_file:
            content = Path(args.content_file).read_text(encoding="utf-8").strip()

        if not title:
            print(json.dumps({"success": False, "message": "缺少标题"}))
            sys.exit(1)

        result = asyncio.run(cmd_publish(
            title=title,
            content=content,
            images=args.images,
            tags=args.tags,
            auto=args.auto,
        ))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result["success"] else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
