"""
小红书 CLI 发布工具 - 基于 Playwright
独立脚本，可被 GUI 或命令行调用

用法:
    python cli_publisher.py --title "标题" --content "正文" --images img1.jpg img2.jpg --tags "#标签1 #标签2"
    python cli_publisher.py --title "标题" --content "正文" --images img1.jpg --auto
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

# Browser data directory
BROWSER_DATA = Path.home() / ".xhs-publisher" / "browser-data"
CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish"


async def publish_note(
    title: str,
    content: str,
    images: list[str] = None,
    tags: str = "",
    auto_publish: bool = False,
    headless: bool = False,
) -> dict:
    """
    发布一条小红书笔记

    Returns:
        {"success": bool, "message": str, "url": str}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"success": False, "message": "playwright 未安装，请运行: pip install playwright"}

    BROWSER_DATA.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # Launch with persistent context (reuse login cookies)
        logger.info("启动浏览器...")
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
            # 1. Navigate to creator publish page
            logger.info("导航到创作者中心发布页...")
            await page.goto(CREATOR_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Check if logged in
            current_url = page.url
            if "login" in current_url.lower() or "customer" in current_url.lower():
                logger.warning("需要登录！请在浏览器窗口中扫码登录")
                if not headless:
                    # Wait for user to login (max 120s)
                    for i in range(120):
                        await page.wait_for_timeout(1000)
                        if "login" not in page.url.lower():
                            logger.info("登录成功！")
                            break
                    else:
                        return {"success": False, "message": "登录超时"}
                else:
                    return {"success": False, "message": "未登录，请先在有头模式下登录"}

            # 2. Switch to "上传图片" tab
            logger.info("切换到上传图片...")
            tab_selectors = [
                ".creator-tab:has-text('图文')",
                ".creator-tab:has-text('上传图文')",
                ".creator-tab:nth-child(3)",
            ]
            tab_clicked = False
            for sel in tab_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=3000)
                        tab_clicked = True
                        logger.info(f"已切换 ({sel})")
                        break
                except:
                    continue

            if not tab_clicked:
                # Fallback: JS click
                await page.evaluate("""
                    () => {
                        const tabs = document.querySelectorAll('.creator-tab');
                        const imgTab = Array.from(tabs).find(t => /图文|图片/.test(t.textContent));
                        if (imgTab) imgTab.click();
                    }
                """)
            await page.wait_for_timeout(2000)

            # 3. Upload images
            if images:
                logger.info(f"上传 {len(images)} 张图片...")
                # Verify files exist
                valid_images = [img for img in images if os.path.exists(img)]
                if not valid_images:
                    return {"success": False, "message": "图片文件不存在"}

                # Find file input
                file_input = page.locator('input[type="file"]').first
                await file_input.set_input_files(valid_images)
                logger.info("图片已上传，等待处理...")
                await page.wait_for_timeout(8000)

                # Wait for upload indicators
                for _ in range(30):
                    has_preview = await page.evaluate("""
                        () => {
                            const indicators = [
                                '.el-upload-list__item',
                                'img[src^="blob:"]',
                                '.note-image-item',
                            ];
                            for (let sel of indicators) {
                                const els = document.querySelectorAll(sel);
                                for (let el of els) {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if has_preview:
                        logger.info("图片上传完成")
                        break
                    await page.wait_for_timeout(1000)

            # 4. Fill title
            logger.info("填写标题...")
            title_selectors = [
                'input[placeholder*="标题"]',
                'input.d-text',
                '#title-input',
                'input[class*="title"]',
            ]
            title_filled = False
            for sel in title_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.fill(title)
                        title_filled = True
                        logger.info(f"标题已填 ({sel})")
                        break
                except:
                    continue

            if not title_filled:
                # JS fallback
                result = await page.evaluate("""
                    (title) => {
                        const inputs = document.querySelectorAll('input');
                        for (const inp of inputs) {
                            const ph = (inp.placeholder || '').toLowerCase();
                            if (ph.includes('标题') || inp.classList.contains('d-text')) {
                                inp.focus();
                                inp.value = title;
                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                return 'ok';
                            }
                        }
                        return 'not found';
                    }
                """, title)
                logger.info(f"标题 JS: {result}")

            await page.wait_for_timeout(1000)

            # 5. Fill content
            logger.info("填写正文...")
            full_content = content
            if tags:
                full_content += "\n\n" + tags

            content_selectors = [
                '[contenteditable="true"]',
                '.ql-editor',
                '#post-textarea',
            ]
            content_filled = False
            for sel in content_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click()
                        await page.wait_for_timeout(300)
                        # Use keyboard to type (more reliable)
                        await loc.evaluate("""
                            (el, text) => {
                                el.innerHTML = text.replace(/\\n/g, '<br>');
                                el.dispatchEvent(new Event('input', {bubbles: true}));
                            }
                        """, full_content)
                        content_filled = True
                        logger.info(f"正文已填 ({sel})")
                        break
                except:
                    continue

            if not content_filled:
                logger.warning("未找到正文编辑区，尝试全部 contenteditable...")
                result = await page.evaluate("""
                    (text) => {
                        const eds = document.querySelectorAll('[contenteditable]');
                        for (let i = 0; i < eds.length; i++) {
                            if (eds[i].textContent.length < 50) {
                                eds[i].focus();
                                eds[i].innerHTML = text.replace(/\\n/g, '<br>');
                                eds[i].dispatchEvent(new Event('input', {bubbles: true}));
                                return 'ok: ' + i;
                            }
                        }
                        return 'not found: ' + eds.length;
                    }
                """, full_content)
                logger.info(f"正文 JS: {result}")

            await page.wait_for_timeout(2000)

            # 6. Take screenshot before publish
            screenshot_path = str(BROWSER_DATA / "pre_publish.png")
            try:
                await page.screenshot(path=screenshot_path)
                logger.info(f"截图: {screenshot_path}")
            except:
                pass

            # 7. Click publish button
            if auto_publish:
                logger.info("点击发布...")
                pub_selectors = [
                    'button:has-text("发布")',
                    'button[class*="publish"]',
                    'button[class*="submit"]',
                ]
                pub_clicked = False
                for sel in pub_selectors:
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            await loc.click(timeout=3000)
                            pub_clicked = True
                            logger.info(f"已点击发布 ({sel})")
                            break
                    except:
                        continue

                if not pub_clicked:
                    await page.evaluate("""
                        () => {
                            const btns = document.querySelectorAll('button');
                            for (const btn of btns) {
                                if (btn.textContent.trim() === '发布' || btn.textContent.trim() === '发布笔记') {
                                    btn.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                await page.wait_for_timeout(5000)
            else:
                logger.info("内容已填写，请在浏览器中手动确认发布")
                # Wait for user to manually publish (max 300s)
                input("按 Enter 确认已发布...")

            # 8. Final screenshot
            final_screenshot = str(BROWSER_DATA / "post_publish.png")
            try:
                await page.screenshot(path=final_screenshot)
            except:
                pass

            return {
                "success": True,
                "message": "发布完成",
                "url": page.url,
                "screenshot": final_screenshot,
            }

        except Exception as e:
            logger.error(f"发布失败: {e}")
            try:
                await page.screenshot(path=str(BROWSER_DATA / "error.png"))
            except:
                pass
            return {"success": False, "message": str(e)}

        finally:
            await context.close()


def main():
    parser = argparse.ArgumentParser(description="小红书 CLI 发布工具")
    parser.add_argument("--title", required=True, help="笔记标题")
    parser.add_argument("--content", required=True, help="笔记正文")
    parser.add_argument("--images", nargs="*", default=[], help="图片路径列表")
    parser.add_argument("--tags", default="", help="话题标签，如 '#标签1 #标签2'")
    parser.add_argument("--auto", action="store_true", help="自动点击发布（不手动确认）")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    result = asyncio.run(publish_note(
        title=args.title,
        content=args.content,
        images=args.images,
        tags=args.tags,
        auto_publish=args.auto,
        headless=args.headless,
    ))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["success"]:
            print(f"✅ {result['message']}")
        else:
            print(f"❌ {result['message']}")
            sys.exit(1)


if __name__ == "__main__":
    main()
