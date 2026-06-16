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
                logger.info(f"📝 开始发布笔记 [{attempt}/{self.max_retries}]: {note.title}")
                result = await self._do_publish(note)
                if result.success:
                    logger.info(f"✅ 发布成功: {note.title}")
                    return result
                else:
                    logger.warning(f"⚠️ 发布失败: {result.message}")
            except Exception as e:
                logger.error(f"❌ 发布异常: {e}")
                result = PublishResult(
                    success=False,
                    note_title=note.title,
                    message=f"异常: {str(e)}",
                )

            if attempt < self.max_retries:
                wait = random.randint(5, 15)
                logger.info(f"⏳ {wait}秒后重试...")
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
        logger.info(f"  [4/8] 上传图片 ({len(note.images)} 张)...")
        if note.images:
            await self._upload_images(page, note.images)
        else:
            logger.warning("  ⚠️ 没有图片，跳过上传")

        # ── 步骤5：填写标题 ──
        logger.info(f"  [5/8] 填写标题: {note.title}")
        await self._fill_title(page, note.title)

        # ── 步骤6：填写正文 ──
        logger.info(f"  [6/8] 填写正文 ({len(note.content)} 字)")
        await self._fill_content(page, note.content)

        # ── 步骤7：添加话题标签 ──
        if note.topics:
            logger.info(f"  [7/8] 添加话题标签: {note.topics}")
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
        """上传图片（支持多图）"""
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
                logger.warning(f"图片不存在: {p}")

        if not valid_paths:
            raise RuntimeError("没有有效的图片文件")

        # 上传文件
        await file_input.set_input_files(valid_paths)
        logger.info(f"  已选择 {len(valid_paths)} 张图片")

        # 等待上传完成
        await self.anti_detect.random_delay(3000, 6000, "等待图片上传")

        # 检查上传是否成功
        for selector in get_selectors("upload_success"):
            try:
                el = await page.query_selector(selector)
                if el:
                    logger.info("  ✅ 图片上传成功")
                    return
            except Exception:
                continue

        logger.info("  图片上传完成（未检测到明确的成功标志）")

    async def _fill_title(self, page: Page, title: str) -> None:
        """填写标题"""
        title_input = await self._find_element(page, "title_input", "标题输入框")
        if not title_input:
            raise RuntimeError("找不到标题输入框")

        await title_input.click()
        await self.anti_detect.random_delay(300, 600, "点击标题框")

        # 清空已有内容
        await title_input.fill("")
        await self.anti_detect.random_delay(200, 400)

        # 模拟人类打字
        for char in title:
            await title_input.type(char, delay=await self.anti_detect.human_type_delay())

        await self.anti_detect.random_delay(500, 1000, "标题填写完成")

    async def _fill_content(self, page: Page, content: str) -> None:
        """填写正文内容"""
        content_input = await self._find_element(page, "content_input", "正文输入框")
        if not content_input:
            raise RuntimeError("找不到正文输入框")

        await content_input.click()
        await self.anti_detect.random_delay(500, 1000, "点击正文框")

        # 分段输入（模拟人类行为）
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
                    logger.warning(f"找不到话题按钮，跳过话题: {topic}")
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
                        logger.info(f"  ✅ 已添加话题: {topic}")
                    else:
                        # 直接按下 Enter 确认
                        await search_input.press("Enter")
                        logger.info(f"  已提交话题: {topic}")

                await self.anti_detect.random_delay(800, 1500, "添加话题后")

            except Exception as e:
                logger.warning(f"添加话题 '{topic}' 失败: {e}")
                continue

    async def _click_publish(self, page: Page) -> bool:
        """点击发布按钮"""
        publish_btn = await self._find_element(page, "publish_button", "发布按钮")
        if not publish_btn:
            logger.error("找不到发布按钮")
            return False

        await publish_btn.click()
        logger.info("  已点击发布按钮")

        # 等待发布结果
        await self.anti_detect.random_delay(3000, 5000, "等待发布结果")

        # 检查是否发布成功
        for selector in get_selectors("publish_success"):
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    return True
            except Exception:
                continue

        # 检查 URL 是否跳转（发布成功通常会跳转）
        if "publish" not in page.url.lower() or "success" in page.url.lower():
            return True

        # 最终检查：如果没有报错信息，也认为成功
        for selector in get_selectors("error"):
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    text = await el.text_content()
                    if text and ("失败" in text or "错误" in text or "error" in text.lower()):
                        logger.error(f"发布出错: {text}")
                        return False
            except Exception:
                continue

        return True

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
            logger.error(f"未找到选择器配置: {selector_name}")
            return None

        for i, selector in enumerate(selectors):
            try:
                el = await page.wait_for_selector(selector, timeout=timeout, state="visible")
                if el:
                    logger.debug(f"  匹配选择器 [{i+1}/{len(selectors)}]: {selector}")
                    return el
            except Exception:
                continue

        logger.warning(f"  ⚠️ 所有选择器均未匹配 [{description}]")
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
            logger.debug(f"📸 截图已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"截图失败: {e}")
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
    ) -> list[PublishResult]:
        """
        批量发布笔记

        Args:
            notes: 笔记列表
            interval_min: 最小发布间隔（秒）
            interval_max: 最大发布间隔（秒）
            scheduled: 是否使用定时发布

        Returns:
            list[PublishResult]: 发布结果列表
        """
        results = []
        total = len(notes)

        for i, note in enumerate(notes, 1):
            logger.info(f"\n{'='*50}")
            logger.info(f"📋 发布进度: {i}/{total}")
            logger.info(f"{'='*50}")

            # 定时发布：等待指定时间
            if scheduled and note.scheduled_time:
                now = datetime.now()
                if note.scheduled_time > now:
                    wait_seconds = (note.scheduled_time - now).total_seconds()
                    logger.info(f"⏰ 定时发布，等待 {wait_seconds/60:.1f} 分钟...")
                    await asyncio.sleep(wait_seconds)

            result = await self.publish_note(note)
            results.append(result)

            # 发布间隔（最后一条不需要等待）
            if i < total:
                interval = random.randint(interval_min, interval_max)
                logger.info(f"⏳ 发布间隔: {interval} 秒...")
                await asyncio.sleep(interval)

        # 统计结果
        success_count = sum(1 for r in results if r.success)
        logger.info(f"\n{'='*50}")
        logger.info(f"📊 批量发布完成: {success_count}/{total} 成功")
        logger.info(f"{'='*50}")

        return results

    # ============================================================
    # 生命周期
    # ============================================================

    async def close(self) -> None:
        """清理资源"""
        try:
            if self._context:
                # 保存最后的 Cookie
                await self.login_manager._save_cookies(self._page)
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("🔒 浏览器已关闭")
        except Exception as e:
            logger.error(f"关闭浏览器异常: {e}")

    async def __aenter__(self):
        await self.init_browser()
        return self

    async def __aexit__(self, *args):
        await self.close()
