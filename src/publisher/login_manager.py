"""
小红书登录管理模块
支持 Cookie 持久化、二维码登录、登录态监控
"""

import json
import os
import asyncio
import logging
import time
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

# ----------------------------------------------------------
# Cookie 加密工具
# ----------------------------------------------------------
try:
    from cryptography.fernet import Fernet
    import base64
    import hashlib

    def _get_cookie_fernet() -> "Fernet":
        """基于环境变量或自动生成的密钥创建 Fernet 实例"""
        passphrase = os.environ.get("XHS_KEY_PASSPHRASE")
        if not passphrase:
            pf = Path.home() / ".xhs_key_passphrase"
            if pf.exists():
                try:
                    passphrase = pf.read_text(encoding="utf-8").strip()
                except Exception:
                    logger.debug("读取密钥文件失败，将自动生成新密钥")
        if not passphrase:
            import secrets
            passphrase = secrets.token_urlsafe(32)
            try:
                pf = Path.home() / ".xhs_key_passphrase"
                pf.parent.mkdir(parents=True, exist_ok=True)
                pf.write_text(passphrase, encoding="utf-8")
            except Exception:
                logger.debug("保存密钥文件失败，将在内存中保留")
        raw_key = hashlib.sha256(passphrase.encode()).digest()
        key = base64.urlsafe_b64encode(raw_key)
        return Fernet(key)

    _COOKIE_FERNET = _get_cookie_fernet()
    _HAS_COOKIE_CRYPTO = True
except ImportError:
    _HAS_COOKIE_CRYPTO = False
    _COOKIE_FERNET = None
    logger.warning("cryptography not installed; cookies stored unencrypted. "
                   "Install with: pip install cryptography")


class LoginManager:
    """
    小红书登录管理器

    功能：
    - Cookie 加密持久化存储与恢复
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
                    logger.warning("Cookie '%s' 已过期", cookie['name'])
                    return False

        # 方法2：检查页面上的登录标志元素
        for selector in get_selectors("login_indicators"):
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    logger.debug("登录标志匹配: %s", selector)
                    return True
            except Exception:
                logger.debug("登录标志选择器 %s 检测异常", selector)
                continue

        # 方法3：检查是否出现登录弹窗
        for selector in get_selectors("not_login_indicators"):
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    logger.debug("检测到未登录标志: %s", selector)
                    return False
            except Exception:
                logger.debug("未登录标志选择器 %s 检测异常", selector)
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
                    logger.debug("创作者中心按钮选择器 %s 检测异常", selector)
                    continue
        except Exception as e:
            logger.debug("创作者中心检测异常: %s", e)

        # 默认假设未登录（安全策略：无法确认时要求重新登录）
        return False

    async def _qr_login_flow(self, page: Page, timeout: int = 300) -> bool:
        """二维码登录流程"""
        logger.info("🔗 请扫描二维码登录...")

        # 导航到登录页
        await page.goto(XHS_LOGIN, wait_until="domcontentloaded")
        await self.anti_detect.random_delay(2000, 3000)

        # 截图保存二维码
        qr_path = self.screenshot_dir / f"qr_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(qr_path))
        logger.info("📸 二维码截图已保存: %s", qr_path)
        logger.info("⏳ 等待扫码登录，超时时间 %s 秒...", timeout)

        # 等待用户扫码
        start_time = asyncio.get_event_loop().time()
        check_interval = 3  # 每3秒检查一次
        last_screenshot_time = start_time  # 追踪上次截图时间

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
                    logger.debug("二维码登录检测选择器 %s 异常", selector)
                    continue

            # 每30秒重新截图（二维码可能刷新）
            now = asyncio.get_event_loop().time()
            if (now - last_screenshot_time) >= 30:
                qr_path = self.screenshot_dir / f"qr_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                await page.screenshot(path=str(qr_path))
                logger.info("📸 二维码截图已更新: %s", qr_path)
                last_screenshot_time = now

        logger.error("❌ 登录超时")
        return False

    async def _save_cookies(self, page: Page) -> None:
        """保存当前上下文的 Cookie（加密存储）"""
        try:
            cookies = await self._context.cookies()
            cookie_data = {
                "cookies": cookies,
                "saved_at": datetime.now().isoformat(),
                "domain": "xiaohongshu.com",
            }
            json_str = json.dumps(cookie_data, ensure_ascii=False, indent=2)

            if _HAS_COOKIE_CRYPTO and _COOKIE_FERNET is not None:
                encrypted = _COOKIE_FERNET.encrypt(json_str.encode("utf-8"))
                self._cookie_file.write_bytes(encrypted)
                logger.info("Cookie 已加密保存至 %s", self._cookie_file)
            else:
                self._cookie_file.write_text(json_str, encoding="utf-8")
                logger.info("Cookie 已保存至 %s (未加密)", self._cookie_file)
        except Exception as e:
            logger.error("保存 Cookie 失败: %s", e)

    async def _load_cookies(self, context: BrowserContext) -> bool:
        """从文件恢复 Cookie（支持加密和明文格式）"""
        try:
            raw = self._cookie_file.read_bytes()

            # 尝试 Fernet 解密
            json_str = None
            if _HAS_COOKIE_CRYPTO and _COOKIE_FERNET is not None:
                try:
                    json_str = _COOKIE_FERNET.decrypt(raw).decode("utf-8")
                except Exception:
                    # 不是 Fernet 格式，当作明文处理
                    logger.debug("Cookie 非 Fernet 加密格式，尝试明文解析")
                    json_str = None

            if json_str is None:
                # 旧格式明文 JSON
                json_str = raw.decode("utf-8")

            data = json.loads(json_str)
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
            logger.error("加载 Cookie 失败: %s", e)
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
                logger.debug("Handled exception")
                pass
