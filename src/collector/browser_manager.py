"""
浏览器管理器

使用 Playwright persistent context 实现 Cookie 复用和登录状态保持。
简化版实现，不依赖数据库，Cookie 存储到本地 JSON 文件。
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, BrowserContext, Page

from .anti_detect import AntiDetect, BrowserFingerprint

logger = logging.getLogger(__name__)


class BrowserManager:
    """
    Playwright 浏览器管理器

    特性：
    - persistent context：Cookie / localStorage 自动持久化
    - 本地 Cookie 文件复用（兜底 persistent context）
    - 自动注入反检测脚本
    - 上下文管理器模式确保资源释放
    """

    DEFAULT_DATA_DIR = os.path.join(
        os.path.expanduser("~"), ".xhs-publisher", "browser-data"
    )
    DEFAULT_COOKIE_FILE = os.path.join(
        os.path.expanduser("~"), ".xhs-publisher", "cookies", "qianfan_cookies.json"
    )

    def __init__(
        self,
        data_dir: Optional[str] = None,
        cookie_file: Optional[str] = None,
        headless: bool = False,
        fingerprint: Optional[BrowserFingerprint] = None,
    ):
        self.data_dir = data_dir or self.DEFAULT_DATA_DIR
        self.cookie_file = cookie_file or self.DEFAULT_COOKIE_FILE
        self.headless = headless
        self.fingerprint = fingerprint or AntiDetect.generate_fingerprint()

        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._initialized = False

    # ── 上下文管理器 ────────────────────────────────────────────────────

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ── 属性 ────────────────────────────────────────────────────────────

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("浏览器未初始化，请先调用 start()")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("浏览器未初始化，请先调用 start()")
        return self._context

    @property
    def is_ready(self) -> bool:
        return self._initialized and self._page is not None

    # ── 启动 ────────────────────────────────────────────────────────────

    async def start(self) -> Page:
        """启动浏览器并返回 Page"""
        if self._initialized:
            return self._page

        logger.info("正在启动浏览器...")

        # 确保目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.cookie_file), exist_ok=True)

        self._playwright = await async_playwright().start()

        # 使用 persistent context 实现 Cookie 持久化
        context_options = AntiDetect.build_context_options(self.fingerprint)
        context_options.update({
            "headless": self.headless,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--start-maximized",
                "--ignore-certificate-errors",
            ],
        })

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.data_dir,
            **context_options,
        )

        # 注入反检测脚本（每个新页面都生效）
        await self._context.add_init_script(AntiDetect.stealth_js(self.fingerprint))

        # 加载本地 Cookie 文件（兜底 persistent context）
        await self._load_cookies()

        # 获取或创建页面
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        self._initialized = True
        logger.info("浏览器启动成功")
        return self._page

    # ── 关闭 ────────────────────────────────────────────────────────────

    async def close(self):
        """保存 Cookie 并关闭浏览器"""
        try:
            if self._context:
                await self._save_cookies()
                await self._context.close()
                logger.debug("浏览器上下文已关闭")
        except Exception as e:
            logger.error(f"关闭浏览器时出错: {e}")
        finally:
            if self._playwright:
                await self._playwright.stop()
            self._playwright = None
            self._context = None
            self._page = None
            self._initialized = False

    # ── Cookie 管理 ─────────────────────────────────────────────────────

    async def _save_cookies(self):
        """保存当前上下文的 Cookie 到本地文件"""
        try:
            cookies = await self._context.cookies()
            if cookies:
                with open(self.cookie_file, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                logger.info(f"Cookie 已保存: {self.cookie_file} ({len(cookies)} 条)")
        except Exception as e:
            logger.error(f"保存 Cookie 失败: {e}")

    async def _load_cookies(self):
        """从本地文件加载 Cookie 到当前上下文"""
        if not os.path.exists(self.cookie_file):
            logger.debug("Cookie 文件不存在，跳过加载")
            return

        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            if cookies:
                await self._context.add_cookies(cookies)
                logger.info(f"Cookie 已加载: {len(cookies)} 条")
        except Exception as e:
            logger.error(f"加载 Cookie 失败: {e}")

    async def save_cookies(self):
        """手动触发 Cookie 保存（公开方法）"""
        await self._save_cookies()

    # ── 登录状态检测 ────────────────────────────────────────────────────

    async def check_login_status(self, url: str = "https://ark.xiaohongshu.com/") -> bool:
        """
        检测千帆后台登录状态（检查当前页面，不刷新）

        返回 True 表示已登录，False 表示需要登录。
        """
        try:
            current_url = self.page.url

            # 被重定向到登录页
            if "login" in current_url or "passport" in current_url:
                logger.info("未登录：当前在登录页")
                return False

            # 检查页面是否包含登录相关元素
            login_btn = await self.page.query_selector(
                'text="登录", button:has-text("登录"), .login-btn, [class*="login"]'
            )
            if login_btn:
                logger.info("未登录：页面存在登录按钮")
                return False

            # 检查是否能正常访问后台内容（如侧边栏、商品管理等）
            sidebar = await self.page.query_selector(
                '[class*="sidebar"], [class*="menu"], [class*="nav"]'
            )
            if sidebar:
                logger.info("已登录：检测到后台导航元素")
                return True

            # 兜底：检查 URL 是否仍在后台域
            if "ark.xiaohongshu.com" in current_url and "login" not in current_url:
                logger.info("已登录：URL 在后台域且非登录页")
                return True

            return False

        except Exception as e:
            logger.error(f"检测登录状态失败: {e}")
            return False

    # ── 扫码登录 ────────────────────────────────────────────────────────

    async def wait_for_qr_login(
        self,
        url: str = "https://ark.xiaohongshu.com/",
        timeout: int = 120,
    ) -> bool:
        """
        等待扫码登录完成

        流程：
        1. 访问千帆后台，触发登录页
        2. 停在登录页等待用户扫码（不刷新页面）
        3. 检测页面跳转确认登录成功
        4. 保存 Cookie
        """
        try:
            # 访问千帆后台（只访问一次）
            logger.info("正在打开千帆后台...")
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)
            
            logger.info("请在浏览器中扫码登录...")
            logger.info(f"等待扫码登录（最多 {timeout} 秒）...")

            # 轮询检测登录状态（不刷新页面）
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                current_url = self.page.url
                
                # 检查是否已离开登录页
                if "login" not in current_url and "passport" not in current_url:
                    # 检查是否在后台页面
                    if "ark.xiaohongshu.com" in current_url:
                        await asyncio.sleep(2)
                        # 再次确认登录状态
                        sidebar = await self.page.query_selector('[class*="sidebar"], [class*="menu"], [class*="nav"]')
                        if sidebar:
                            await self._save_cookies()
                            logger.info("扫码登录成功，Cookie 已保存")
                            return True
                
                # 等待2秒再检测
                await asyncio.sleep(2)

            logger.warning("扫码登录超时")
            return False

        except Exception as e:
            logger.error(f"扫码登录流程出错: {e}")
            return False

    # ── 页面操作辅助 ────────────────────────────────────────────────────

    async def new_page(self) -> Page:
        """创建新标签页（自动注入反检测脚本）"""
        page = await self._context.new_page()
        return page

    async def goto(self, url: str, **kwargs) -> None:
        """导航到指定 URL，带随机延迟"""
        await self.page.goto(url, wait_until="domcontentloaded", **kwargs)
        await AntiDetect.human_like_delay(1.0, 2.5)

    async def screenshot(self, path: str, **kwargs) -> None:
        """截图"""
        await self.page.screenshot(path=path, **kwargs)
