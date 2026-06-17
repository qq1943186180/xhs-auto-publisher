"""
小红书自动发布模块
核心发布流程：登录 → 创建 → 上传图片 → 填写内容 → 添加话题 → 发布
"""

import asyncio
import logging
import random
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright, ElementHandle

from .login_manager import LoginManager
from .anti_detect import AntiDetect
from .selectors import get_selectors

logger = logging.getLogger("xhs.publisher")

# 小红书 URL
XHS_CREATOR = "https://creator.xiaohongshu.com"
XHS_PUBLISH = "https://creator.xiaohongshu.com/publish/publish"


@dataclass
class NoteData:
    """小红书笔记数据"""
    title: str                              # 标题（最多20字）
    content: str                            # 正文内容
    images: list[str] = field(default_factory=list)   # 图片路径列表
    topics: list[str] = field(default_factory=list)    # 话题标签
    location: str = ""                       # 位置
    scheduled_time: Optional[datetime] = None  # 定时发布时间

    def __post_init__(self):
        """验证字段"""
        if len(self.title) > 20:
            raise ValueError(f"标题长度 {len(self.title)} 超过限制 20 字: {self.title[:30]}")
        if len(self.content) > 10000:
            raise ValueError(f"正文长度 {len(self.content)} 超过限制 10000 字")


@dataclass
class PublishResult:
    """发布结果"""
    success: bool
    note_title: str
    message: str = ""
    screenshot_path: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class XhsPublisher:
    """
    小红书自动发布器

    使用流程：
    1. 初始化 XhsPublisher 实例
    2. 调用 init_browser() 启动浏览器
    3. 调用 login() 完成登录
    4. 调用 publish_note() 发布单条笔记
    5. 调用 batch_publish() 批量发布
    6. 调用 close() 清理资源
    """

    def __init__(
        self,
        data_dir: str = "./data",
        headless: bool = False,
        max_retries: int = 3,
    ):
        self.data_dir = Path(data_dir)
        self.screenshot_dir = self.data_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self.headless = headless
        self.max_retries = max_retries

        self.anti_detect = AntiDetect()
        self.login_manager = LoginManager(
            cookie_dir=str(self.data_dir / "cookies"),
            screenshot_dir=str(self.screenshot_dir),
        )

        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._playwright = None
        self._browser = None

    async def init_browser(self) -> None:
        """初始化浏览器"""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=self.anti_detect.get_launch_args(),
        )

        viewport = self.anti_detect.get_random_viewport()
        self._context = await self._browser.new_context(
            viewport=viewport,
            user_agent=self.anti_detect.user_agent,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        # 注入反检测脚本
        await self.anti_detect.apply_stealth(self._context)

        # 创建页面
        self._page = await self._context.new_page()

        # 设置默认超时
        self._page.set_default_timeout(30000)
        self._page.set_default_navigation_timeout(60000)

        logger.info("✅ 浏览器初始化完成")

    async def login(self, timeout: int = 300) -> bool:
        """
        完成登录流程

        Args:
            timeout: 登录超时时间（秒）

        Returns:
            bool: 登录是否成功
        """
        if not self._page:
            raise RuntimeError("请先调用 init_browser()")

        # 尝试恢复 Cookie
        if self.login_manager._cookie_file.exists():
            await self.login_manager._load_cookies(self._context)

        return await self.login_manager.ensure_login(self._page, timeout)

    async def publish_note(self, note: NoteData) -> PublishResult:
        """
        发布单条笔记（带重试）

        Args:
            note: 笔记数据

        Returns:
            PublishResult: 发布结果
        """
        if not self._page:
            raise RuntimeError("请先调用 init_browser() 和 login()")

        for attempt in range(1, self.max_retries + 1):
            try:
                # 重试前刷新页面，确保干净状态
                if attempt > 1:
                    logger.info("🔄 重试前刷新页面...")
                    await self._page.goto(XHS_PUBLISH, wait_until="domcontentloaded")
                    await self.anti_detect.random_delay(2000, 3000, "重试前刷新")

                logger.info("📝 开始发布笔记 [%s/%s]: %s", attempt, self.max_retries, note.title)
                result = await self._do_publish(note)
                if result.success:
                    logger.info("✅ 发布成功: %s", note.title)
                    return result
                else:
                    logger.warning("⚠️ 发布失败: %s", result.message)
            except Exception as e:
                logger.error("❌ 发布异常: %s", e)
                result = PublishResult(
                    success=False,
                    note_title=note.title,
                    message=f"异常: {str(e)}",
                )

            if attempt < self.max_retries:
                wait = random.randint(5, 15)
                logger.info("⏳ %s秒后重试...", wait)
                await asyncio.sleep(wait)

        # 所有重试都失败
        await self._take_screenshot(f"publish_failed_{note.title[:10]}")
        return PublishResult(
            success=False,
            note_title=note.title,
            message=f"重试 {self.max_retries} 次后仍失败",
        )

    async def _do_publish(self, note: NoteData) -> PublishResult:
        """执行发布流程的核心逻辑"""
        page = self._page

        # ── 步骤1：检查登录状态 ──
        logger.info("  [1/8] 检查登录状态...")
        is_logged = await self.login_manager.refresh_login_if_needed(page)
        if not is_logged:
            return PublishResult(
                success=False,
                note_title=note.title,
                message="登录态失效",
            )

        # ── 步骤2：导航到发布页面 ──
        logger.info("  [2/8] 导航到发布页面...")
        await page.goto(XHS_PUBLISH, wait_until="domcontentloaded")
        await self.anti_detect.random_delay(2000, 3000, "发布页面加载")

        # 关闭可能出现的弹窗
        await self._dismiss_popups(page)

        # ── 步骤3：切换到图文 tab ──
        logger.info("  [3/8] 切换到图文模式...")
        await self._click_with_fallback(page, "upload_tab_image", "图文tab")
        await self.anti_detect.random_delay(1000, 2000, "切换tab后")

        # ── 步骤4：上传图片 ──
        logger.info("  [4/8] 上传图片 (%s 张)...", len(note.images))
        if note.images:
            await self._upload_images(page, note.images)
        else:
            logger.warning("  ⚠️ 没有图片，跳过上传")

        # ── 步骤5：填写标题 ──
        logger.info("  [5/8] 填写标题: %s", note.title)
        await self._fill_title(page, note.title)

        # ── 步骤6：填写正文 ──
        logger.info("  [6/8] 填写正文 (%s 字)", len(note.content))
        await self._fill_content(page, note.content)

        # ── 步骤7：添加话题标签 ──
        if note.topics:
            logger.info("  [7/8] 添加话题标签: %s", note.topics)
            await self._add_topics(page, note.topics)
        else:
            logger.info("  [7/8] 无话题标签，跳过")

        # 发布前截图
        await self._take_screenshot(f"before_publish_{note.title[:10]}")

        # ── 步骤8：点击发布 ──
        logger.info("  [8/8] 点击发布按钮...")
        publish_result = await self._click_publish(page)

        if publish_result:
            await self.anti_detect.random_delay(2000, 4000, "发布后等待")
            await self._take_screenshot(f"publish_success_{note.title[:10]}")
            return PublishResult(
                success=True,
                note_title=note.title,
                message="发布成功",
            )
        else:
            return PublishResult(
                success=False,
                note_title=note.title,
                message="点击发布按钮失败或未检测到发布成功",
            )

    # ============================================================
    # 内部方法：各步骤的具体实现
    # ============================================================

    async def _upload_images(self, page: Page, image_paths: list[str]) -> None:
        """
        上传图片（支持多图）

        轮询等待：每 2s 检查上传成功标志，最大 60s
        """
        # 找到文件输入框
        file_input = await self._find_element(page, "file_input", "文件上传输入框")
        if not file_input:
            raise RuntimeError("找不到文件上传输入框")

        # 验证图片路径
        valid_paths = []
        for p in image_paths:
            path = Path(p)
            if path.exists():
                valid_paths.append(str(path.absolute()))
            else:
                logger.warning("图片不存在: %s", p)

        if not valid_paths:
            raise RuntimeError("没有有效的图片文件")

        # 上传文件
        await file_input.set_input_files(valid_paths)
        logger.info("  已选择 %s 张图片", len(valid_paths))

        # 轮询等待上传完成：每 2s 检查，最大 60s
        max_wait = 60
        poll_interval = 2
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # 检查上传成功标志
            for selector in get_selectors("upload_success"):
                try:
                    el = await page.query_selector(selector)
                    if el and await el.is_visible():
                        logger.info("  ✅ 图片上传成功 (耗时 %ss)", elapsed)
                        return
                except Exception:
                    logger.debug("上传成功检测选择器 %s 异常", selector)
                    continue

            logger.debug("  等待上传中... (%s/%ss)", elapsed, max_wait)

        logger.info("  图片上传完成（超时未检测到成功标志，继续流程）")

    async def _fill_title(self, page: Page, title: str, fast_mode: bool = False) -> None:
        """
        填写标题

        Args:
            fast_mode: True=一次性 fill() 填入（快速），False=逐字拟人输入
        """
        title_input = await self._find_element(page, "title_input", "标题输入框")
        if not title_input:
            raise RuntimeError("找不到标题输入框")

        await title_input.click()
        await self.anti_detect.random_delay(300, 600, "点击标题框")

        # 清空已有内容
        await title_input.fill("")
        await self.anti_detect.random_delay(200, 400)

        if fast_mode:
            # 快速模式：一次性填入
            await title_input.fill(title)
        else:
            # 拟人模式：逐字输入带随机延迟
            for char in title:
                await title_input.type(char, delay=await self.anti_detect.human_type_delay())

        await self.anti_detect.random_delay(500, 1000, "标题填写完成")

    async def _fill_content(self, page: Page, content: str, fast_mode: bool = False) -> None:
        """
        填写正文内容

        Args:
            fast_mode: True=一次性填入（快速），False=分段拟人输入
        """
        content_input = await self._find_element(page, "content_input", "正文输入框")
        if not content_input:
            raise RuntimeError("找不到正文输入框")

        await content_input.click()
        await self.anti_detect.random_delay(500, 1000, "点击正文框")

        if fast_mode:
            # 快速模式：一次性填入
            await content_input.fill(content)
        else:
            # 拟人模式：分段输入（模拟人类行为）
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.strip():
                    # 逐字输入
                    for char in line:
                        await content_input.type(char, delay=await self.anti_detect.human_type_delay())

                # 换行
                if i < len(lines) - 1:
                    await content_input.press("Enter")
                    await self.anti_detect.random_delay(100, 300)

        await self.anti_detect.random_delay(500, 1000, "正文填写完成")

    async def _add_topics(self, page: Page, topics: list[str]) -> None:
        """添加话题标签"""
        for topic in topics:
            try:
                # 点击话题按钮
                topic_btn = await self._find_element(page, "topic_button", "话题按钮")
                if not topic_btn:
                    logger.warning("找不到话题按钮，跳过话题: %s", topic)
                    continue

                await topic_btn.click()
                await self.anti_detect.random_delay(500, 1000, "点击话题按钮")

                # 搜索话题
                search_input = await self._find_element(page, "topic_search_input", "话题搜索框")
                if search_input:
                    await search_input.fill("")
                    await self.anti_detect.random_delay(200, 400)

                    # 输入话题名称
                    for char in topic:
                        await search_input.type(char, delay=await self.anti_detect.human_type_delay())

                    await self.anti_detect.random_delay(1000, 2000, "等待话题搜索结果")

                    # 选择第一个搜索结果
                    result = await self._find_element(page, "topic_search_result", "话题搜索结果")
                    if result:
                        await result.click()
                        logger.info("  ✅ 已添加话题: %s", topic)
                    else:
                        # 直接按下 Enter 确认
                        await search_input.press("Enter")
                        logger.info("  已提交话题: %s", topic)

                await self.anti_detect.random_delay(800, 1500, "添加话题后")

            except Exception as e:
                logger.warning("添加话题 '%s' 失败: %s", topic, e)
                continue

    async def _click_publish(self, page: Page) -> bool:
        """点击发布按钮，加强发布成功判定"""
        publish_btn = await self._find_element(page, "publish_button", "发布按钮")
        if not publish_btn:
            logger.error("找不到发布按钮")
            return False

        await publish_btn.click()
        logger.info("  已点击发布按钮")

        # 等待发布结果：轮询检测 URL 变化 或 Toast 出现
        initial_url = page.url
        for _ in range(10):  # 最多等 20s
            await asyncio.sleep(2)

            # 检查 URL 是否变化（发布成功通常跳转）
            if page.url != initial_url:
                logger.info("  ✅ 检测到 URL 跳转: %s", page.url)
                return True

            # 检查成功 Toast / 提示
            for selector in get_selectors("publish_success"):
                try:
                    el = await page.query_selector(selector)
                    if el and await el.is_visible():
                        logger.info("  ✅ 检测到发布成功标志: %s", selector)
                        return True
                except Exception:
                    logger.debug("发布成功检测选择器 %s 异常", selector)
                    continue

            # 检查是否有错误提示
            has_error = False
            for selector in get_selectors("error"):
                try:
                    el = await page.query_selector(selector)
                    if el and await el.is_visible():
                        text = await el.text_content()
                        if text and ("失败" in text or "错误" in text or "error" in text.lower()):
                            logger.error("发布出错: %s", text)
                            has_error = True
                            break
                except Exception:
                    logger.debug("错误检测选择器 %s 异常", selector)
                    continue
            if has_error:
                return False

        # 超过 20s 仍无明确结果，也检查下页面状态
        logger.warning("  ⚠️ 发布结果未明确检测到（超时），检查页面状态...")
        # 最终检查：如果 URL 没变且没有错误，可能仍在发布中或已成功
        if "publish" not in page.url.lower() or "success" in page.url.lower():
            return True

        return False

    # ============================================================
    # 工具方法
    # ============================================================

    async def _find_element(
        self,
        page: Page,
        selector_name: str,
        description: str,
        timeout: int = 5000,
    ) -> Optional[ElementHandle]:
        """
        使用 fallback 选择器查找元素

        Args:
            page: 页面对象
            selector_name: 选择器名称（对应 selectors.py 中的 key）
            description: 元素描述（用于日志）
            timeout: 每个选择器的超时时间

        Returns:
            ElementHandle 或 None
        """
        selectors = get_selectors(selector_name)
        if not selectors:
            logger.error("未找到选择器配置: %s", selector_name)
            return None

        for i, selector in enumerate(selectors):
            try:
                el = await page.wait_for_selector(selector, timeout=timeout, state="visible")
                if el:
                    logger.debug("  匹配选择器 [%s/%s]: %s", i+1, len(selectors), selector)
                    return el
            except Exception:
                logger.debug("  选择器 %s 超时或异常", selector)
                continue

        logger.warning("  ⚠️ 所有选择器均未匹配 [%s]", description)
        return None

    async def _click_with_fallback(
        self,
        page: Page,
        selector_name: str,
        description: str,
    ) -> bool:
        """使用 fallback 选择器点击元素"""
        element = await self._find_element(page, selector_name, description)
        if element:
            await element.click()
            return True
        return False

    async def _dismiss_popups(self, page: Page) -> None:
        """关闭可能出现的弹窗"""
        for selector in get_selectors("close_popup"):
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click()
                    await self.anti_detect.random_delay(300, 600, "关闭弹窗")
            except Exception:
                logger.debug("弹窗关闭选择器 %s 异常", selector)
                continue

    async def _take_screenshot(self, name: str) -> str:
        """保存截图"""
        if not self._page:
            return ""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{name}_{timestamp}.png"
            filepath = self.screenshot_dir / filename
            await self._page.screenshot(path=str(filepath), full_page=True)
            logger.debug("📸 截图已保存: %s", filepath)
            return str(filepath)
        except Exception as e:
            logger.error("截图失败: %s", e)
            return ""

    # ============================================================
    # 批量发布
    # ============================================================

    async def batch_publish(
        self,
        notes: list[NoteData],
        interval_min: int = 60,
        interval_max: int = 180,
        scheduled: bool = False,
        progressive: bool = True,
    ) -> list[PublishResult]:
        """
        批量发布笔记

        Args:
            notes: 笔记列表
            interval_min: 最小发布间隔（秒）
            interval_max: 最大发布间隔（秒）
            scheduled: 是否使用定时发布
            progressive: 是否渐进式间隔（前几条短，后续加长）

        Returns:
            list[PublishResult]: 发布结果列表
        """
        results = []
        total = len(notes)

        for i, note in enumerate(notes, 1):
            logger.info("\n%s", '='*50)
            logger.info("📋 发布进度: %s/%s", i, total)
            logger.info("%s", '='*50)

            # 定时发布：等待指定时间
            if scheduled and note.scheduled_time:
                now = datetime.now()
                if note.scheduled_time > now:
                    wait_seconds = (note.scheduled_time - now).total_seconds()
                    logger.info("定时发布，等待 %.1f 分钟...", wait_seconds/60)
                    await asyncio.sleep(wait_seconds)

            result = await self.publish_note(note)
            results.append(result)

            # 发布间隔（最后一条不需要等待）
            if i < total:
                if progressive and i <= 3:
                    # 前几条间隔较短
                    interval = random.randint(max(30, interval_min // 2), interval_min)
                else:
                    interval = random.randint(interval_min, interval_max)
                logger.info("⏳ 发布间隔: %s 秒...", interval)
                await asyncio.sleep(interval)

        # 统计结果
        success_count = sum(1 for r in results if r.success)
        logger.info("\n%s", '='*50)
        logger.info("📊 批量发布完成: %s/%s 成功", success_count, total)
        logger.info("%s", '='*50)

        return results

    # ============================================================
    # 生命周期
    # ============================================================

    async def close(self) -> None:
        """清理资源"""
        try:
            if self._page:
                # 保存最后的 Cookie
                await self.login_manager._save_cookies(self._page)
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("🔒 浏览器已关闭")
        except Exception as e:
            logger.error("关闭浏览器异常: %s", e)

    async def __aenter__(self):
        await self.init_browser()
        return self

    async def __aexit__(self, *args):
        await self.close()
