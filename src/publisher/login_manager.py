"""
小红书登录管理模块
支持 Cookie 持久化、二维码登录、登录态监控
"""

import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from .anti_detect import AntiDetect
from .selectors import get_selectors

logger = logging.getLogger("xhs.login")

# 小红书 URL
XHS_HOME = "https://www.xiaohongshu.com"
XHS_CREATOR = "https://creator.xiaohongshu.com"
XHS_LOGIN = "https://www.xiaohongshu.com/login"


class LoginManager:
    """
    小红书登录管理器

    功能：
    - Cookie 持久化存储与恢复
    - 登录状态检测
    - 二维码登录流程
    - 登录态定期刷新
    """

    def __init__(
        self,
        cookie_dir: str = "./data/cookies",
        screenshot_dir: str = "./data/screenshots",
    ):
        self.cookie_dir = Path(cookie_dir)
        self.screenshot_dir = Path(screenshot_dir)
        self.cookie_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self.anti_detect = AntiDetect()
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._logged_in: bool = False
        self._last_check: Optional[datetime] = None
        self._cookie_file = self.cookie_dir / "xhs_cookies.json"

    async def get_authenticated_context(
        self,
        headless: bool = False,
        browser_type: str = "chromium",
    ) -> BrowserContext:
        """
        获取已认证的浏览器上下文
        优先恢复 Cookie，若失效则走登录流程
        """
        pw = await async_playwright().start()

        # 启动浏览器
        browser = await getattr(pw, browser_type).launch(
            headless=headless,
            args=self.anti_detect.get_launch_args(),
        )

        # 创建 context（使用 persistent context 支持 Cookie）
        viewport = self.anti_detect.get_random_viewport()
        context = await browser.new_context(
            viewport=viewport,
            user_agent=self.anti_detect.user_agent,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        # 注入反检测脚本
        await self.anti_detect.apply_stealth(context)

        # 尝试恢复 Cookie
        if self._cookie_file.exists():
            await self._load_cookies(context)
            logger.info("已加载保存的 Cookie")

        self._context = context
        return context

    async def ensure_login(
        self,
        page: Page,
        timeout: int = 300,
    ) -> bool:
        """
        确保已登录状态
        如果未登录，触发登录流程

        Args:
            page: Playwright Page 对象
            timeout: 登录超时时间（秒）

        Returns:
            bool: 是否登录成功
        """
        self._page = page

        # 先导航到首页
        await page.goto(XHS_HOME, wait_until="domcontentloaded")
        await self.anti_detect.random_delay(2000, 3000, "等待页面加载")

        # 检查登录状态
        if await self._check_login_status(page):
            logger.info("✅ 登录状态有效")
            self._logged_in = True
            self._last_check = datetime.now()
            await self._save_cookies(page)
            return True

        # 需要登录 - 启动二维码登录流程
        logger.info("⚠️ 未登录，启动登录流程...")
        return await self._qr_login_flow(page, timeout)

    async def _check_login_status(self, page: Page) -> bool:
        """检查当前页面的登录状态"""
        # 方法1：检查 Cookie 中的登录标识
        cookies = await self._context.cookies("https://www.xiaohongshu.com")
        login_cookies = [c for c in cookies if c["name"] in ("web_session", "xsecappid", "a1")]
        if not login_cookies:
            logger.debug("缺少关键登录 Cookie")
            return False

        # 检查 Cookie 是否过期
        for cookie in login_cookies:
            if cookie.get("expires", 0) > 0:
                expire_time = datetime.fromtimestamp(cookie["expires"])
                if expire_time < datetime.now():
                    logger.warning(f"Cookie '{cookie['name']}' 已过期")
                    return False

        # 方法2：检查页面上的登录标志元素
        for selector in get_selectors("login_indicators"):
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    logger.debug(f"登录标志匹配: {selector}")
                    return True
            except Exception:
                continue

        # 方法3：检查是否出现登录弹窗
        for selector in get_selectors("not_login_indicators"):
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    logger.debug(f"检测到未登录标志: {selector}")
                    return False
            except Exception:
                continue

        # 方法4：尝试访问创作者中心
        try:
            resp = await page.goto(XHS_CREATOR, wait_until="domcontentloaded")
            if resp and resp.url and "login" in resp.url.lower():
                return False
            # 检查创作者中心页面是否正常
            for selector in get_selectors("create_button"):
                try:
                    el = await page.query_selector(selector)
                    if el:
                        return True
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"创作者中心检测异常: {e}")

        # 默认假设已登录（保守策略）
        return True

    async def _qr_login_flow(self, page: Page, timeout: int = 300) -> bool:
        """二维码登录流程"""
        logger.info("🔗 请扫描二维码登录...")

        # 导航到登录页
        await page.goto(XHS_LOGIN, wait_until="domcontentloaded")
        await self.anti_detect.random_delay(2000, 3000)

        # 截图保存二维码
        qr_path = self.screenshot_dir / f"qr_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(qr_path))
        logger.info(f"📸 二维码截图已保存: {qr_path}")
        logger.info(f"⏳ 等待扫码登录，超时时间 {timeout} 秒...")

        # 等待用户扫码
        start_time = asyncio.get_event_loop().time()
        check_interval = 3  # 每3秒检查一次

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(check_interval)

            # 检查是否已登录（URL 跳转或出现用户信息）
            current_url = page.url
            if "login" not in current_url.lower():
                # 再确认一下登录状态
                if await self._check_login_status(page):
                    logger.info("✅ 二维码登录成功！")
                    self._logged_in = True
                    self._last_check = datetime.now()
                    await self._save_cookies(page)
                    return True

            # 检查页面上是否出现了已登录标志
            for selector in get_selectors("login_indicators"):
                try:
                    el = await page.query_selector(selector)
                    if el and await el.is_visible():
                        logger.info("✅ 二维码登录成功！")
                        self._logged_in = True
                        self._last_check = datetime.now()
                        await self._save_cookies(page)
                        return True
                except Exception:
                    continue

            # 每30秒重新截图（二维码可能刷新）
            elapsed = asyncio.get_event_loop().time() - start_time
            if int(elapsed) % 30 < check_interval:
                qr_path = self.screenshot_dir / f"qr_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                await page.screenshot(path=str(qr_path))
                logger.info(f"📸 二维码截图已更新: {qr_path}")

        logger.error("❌ 登录超时")
        return False

    async def _save_cookies(self, page: Page) -> None:
        """保存当前上下文的 Cookie"""
        try:
            cookies = await self._context.cookies()
            cookie_data = {
                "cookies": cookies,
                "saved_at": datetime.now().isoformat(),
                "domain": "xiaohongshu.com",
            }
            self._cookie_file.write_text(
                json.dumps(cookie_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"Cookie 已保存至 {self._cookie_file}")
        except Exception as e:
            logger.error(f"保存 Cookie 失败: {e}")

    async def _load_cookies(self, context: BrowserContext) -> bool:
        """从文件恢复 Cookie"""
        try:
            data = json.loads(self._cookie_file.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            if not cookies:
                return False

            # 检查保存时间
            saved_at = data.get("saved_at", "")
            if saved_at:
                saved_time = datetime.fromisoformat(saved_at)
                if datetime.now() - saved_time > timedelta(days=7):
                    logger.warning("Cookie 已超过 7 天，可能已失效")
                    return False

            await context.add_cookies(cookies)
            return True
        except Exception as e:
            logger.error(f"加载 Cookie 失败: {e}")
            return False

    async def refresh_login_if_needed(
        self,
        page: Page,
        interval_minutes: int = 30,
    ) -> bool:
        """
        定期检查并刷新登录态

        Args:
            page: 当前页面
            interval_minutes: 检查间隔（分钟）

        Returns:
            bool: 登录态是否有效
        """
        if self._last_check:
            elapsed = datetime.now() - self._last_check
            if elapsed < timedelta(minutes=interval_minutes):
                return self._logged_in

        logger.info("🔄 检查登录态...")
        is_logged_in = await self._check_login_status(page)
        self._last_check = datetime.now()

        if is_logged_in:
            self._logged_in = True
            await self._save_cookies(page)
        else:
            logger.warning("⚠️ 登录态已失效，需要重新登录")
            self._logged_in = False

        return self._logged_in

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    async def close(self) -> None:
        """关闭并清理"""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
