"""
千帆后台产品图采集器

采集小红书千帆后台（https://ark.xiaohongshu.com/）的商品数据和图片。
支持分页采集、断点续传、数据导出。

用法：
    async with QianfanCollector() as collector:
        # 首次使用会弹出浏览器等待扫码登录
        if not await collector.ensure_login():
            logger.info("登录失败")
            return

        # 采集所有商品
        products = await collector.collect_all_products()
        logger.info("采集到 %s 个商品", len(products))

        # 下载图片
        await collector.download_all_images(products)

        # 导出数据（完整 + 简化）
        collector.export_json(products)
        collector.export_simple(products)
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from .anti_detect import AntiDetect
from .browser_manager import BrowserManager

logger = logging.getLogger(__name__)
DEFAULT_IMAGES_PER_PRODUCT = 5


# ── 数据结构 ────────────────────────────────────────────────────────────────

class Product:
    """商品数据模型"""

    def __init__(self):
        self.item_id: str = ""
        self.name: str = ""
        self.price: str = ""
        self.original_price: str = ""
        self.status: str = ""  # 上架/下架/审核中
        self.main_images: List[str] = []    # 主图 URL 列表
        self.detail_images: List[str] = []  # 详情图 URL 列表
        self.skus: List[Dict[str, Any]] = []  # SKU 信息
        self.category: str = ""
        self.local_images: List[str] = []   # 下载后的本地路径

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "price": self.price,
            "original_price": self.original_price,
            "status": self.status,
            "category": self.category,
            "main_images": self.main_images,
            "detail_images": self.detail_images,
            "skus": self.skus,
            "local_images": self.local_images,
        }


# ── 采集器 ──────────────────────────────────────────────────────────────────

class QianfanCollector:
    """
    千帆后台产品图采集器

    特性：
    - Cookie 复用 + 扫码登录
    - 分页采集商品列表
    - 主图 / 详情图下载
    - 断点续传（跳过已下载图片）
    - JSON 数据导出
    """

    # 千帆后台 URL 常量
    BASE_URL = "https://ark.xiaohongshu.com"
    # 商品管理页面
    GOODS_LIST_URL = f"{BASE_URL}/app-item/list/shelf"

    # 默认输出目录
    DEFAULT_OUTPUT_DIR = os.path.join(
        os.path.expanduser("~"), ".xhs-publisher", "collected"
    )

    def __init__(
        self,
        output_dir: Optional[str] = None,
        headless: bool = False,
        cookie_file: Optional[str] = None,
        data_dir: Optional[str] = None,
        images_per_product: int = DEFAULT_IMAGES_PER_PRODUCT,
    ):
        self.output_dir = output_dir or self.DEFAULT_OUTPUT_DIR
        self.headless = headless
        self.cookie_file = cookie_file
        self.data_dir = data_dir
        self.images_per_product = max(1, int(images_per_product or DEFAULT_IMAGES_PER_PRODUCT))

        self._browser: Optional[BrowserManager] = None
        self._progress_file = os.path.join(self.output_dir, ".download_progress.json")
        self._downloaded: set = set()  # 已下载图片 URL 集合

    # ── 上下文管理器 ────────────────────────────────────────────────────

    async def __aenter__(self):
        self._browser = BrowserManager(
            headless=self.headless,
            cookie_file=self.cookie_file,
            data_dir=self.data_dir,
        )
        await self._browser.start()
        self._load_progress()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()

    @property
    def page(self):
        return self._browser.page

    # ── 登录管理 ────────────────────────────────────────────────────────

    async def ensure_login(self) -> bool:
        """
        确保已登录千帆后台

        优先使用已有 Cookie，失败则等待扫码登录。
        """
        # 先检测是否已登录
        is_logged = await self._browser.check_login_status(self.BASE_URL)
        if is_logged:
            logger.info("使用已有 Cookie 登录成功")
            return True

        # Cookie 失效或不存在，等待扫码登录
        logger.info("Cookie 无效或不存在，启动扫码登录流程...")
        return await self._browser.wait_for_qr_login(self.BASE_URL)

    # ── 商品列表采集 ────────────────────────────────────────────────────

    async def collect_all_products(self, max_pages: int = 0) -> List[Product]:
        """
        采集所有商品

        Args:
            max_pages: 最大采集页数，0 表示不限制

        Returns:
            商品列表
        """
        all_products: List[Product] = []
        page_num = 1

        # 导航到商品管理页
        logger.info("正在访问商品管理页: %s", self.GOODS_LIST_URL)
        await self._browser.goto(self.GOODS_LIST_URL)
        await AntiDetect.human_like_delay(2.0, 4.0)

        while True:
            if max_pages > 0 and page_num > max_pages:
                logger.info("已达到最大采集页数: %s", max_pages)
                break

            logger.info("正在采集第 %s 页...", page_num)
            page_products = await self._collect_current_page()

            if not page_products:
                logger.info("当前页无商品数据，采集结束")
                break

            all_products.extend(page_products)
            logger.info(
                f"第 {page_num} 页采集完成，本页 {len(page_products)} 个商品，"
                f"累计 {len(all_products)} 个"
            )

            # 翻页
            has_next = await self._go_next_page()
            if not has_next:
                logger.info("没有下一页了")
                break

            page_num += 1
            await AntiDetect.human_like_delay(1.5, 3.5)

        logger.info("商品采集完成，共 %s 个商品", len(all_products))
        return all_products

    async def _collect_current_page(self) -> List[Product]:
        """采集当前页面的商品列表"""
        products: List[Product] = []

        # 等待商品列表加载
        # 注意：以下选择器需要根据千帆后台实际 DOM 结构调整
        # 千帆后台通常使用 React/Vue 渲染，商品卡片可能在 table 或 card 容器中
        await self._wait_for_goods_list()

        # 尝试多种选择器策略
        goods_items = await self._find_goods_items()

        if not goods_items:
            logger.warning("未找到商品列表元素，可能需要更新选择器")
            # 截图保存以便调试
            await self._debug_screenshot("no_goods_found")
            return products

        for item_el in goods_items:
            try:
                product = await self._parse_product_item(item_el)
                if product and product.name:
                    products.append(product)
            except Exception as e:
                logger.error("解析商品项出错: %s", e)
                continue

        return products

    async def _wait_for_goods_list(self, timeout: int = 15000):
        """等待商品列表加载完成"""
        # 尝试多种可能的选择器
        selectors = [
            # 常见的商品列表容器选择器
            '[class*="goods-list"]',
            '[class*="product-list"]',
            '[class*="item-list"]',
            'table tbody tr',
            '[class*="card"]',
            # Vue/React 渲染的列表
            '[class*="list"] [class*="item"]',
            '[class*="table"] [class*="row"]',
        ]

        for selector in selectors:
            try:
                await self.page.wait_for_selector(selector, timeout=3000)
                logger.debug("商品列表已加载: %s", selector)
                return
            except Exception:
                continue

        # 所有选择器都未匹配，等待固定时间
        logger.warning("未匹配到已知商品列表选择器，等待页面加载...")
        await asyncio.sleep(5)

    async def _find_goods_items(self):
        """查找商品列表项元素"""
        # 策略1：table 行
        rows = await self.page.query_selector_all('table tbody tr')
        if rows and len(rows) > 0:
            logger.debug("通过 table 行找到 %s 个商品", len(rows))
            return rows

        # 策略2：card 容器
        cards = await self.page.query_selector_all(
            '[class*="goods-card"], [class*="product-card"], [class*="item-card"]'
        )
        if cards and len(cards) > 0:
            logger.debug("通过 card 找到 %s 个商品", len(cards))
            return cards

        # 策略3：通用列表项
        items = await self.page.query_selector_all(
            '[class*="goods-item"], [class*="product-item"], [class*="list-item"]'
        )
        if items and len(items) > 0:
            logger.debug("通过 list-item 找到 %s 个商品", len(items))
            return items

        # 策略4：通过商品图片反查
        imgs = await self.page.query_selector_all('img[src*="goods"], img[src*="product"]')
        if imgs:
            # 向上查找父容器
            parent_items = set()
            for img in imgs:
                parent = await img.evaluate_handle(
                    'el => el.closest("[class*=item], [class*=card], tr")'
                )
                if parent:
                    parent_items.add(parent)
            if parent_items:
                logger.debug("通过图片反查找到 %s 个商品", len(parent_items))
                return list(parent_items)

        return []

    async def _parse_product_item(self, element) -> Optional[Product]:
        """解析单个商品元素"""
        product = Product()

        # ── 商品名称 ────────────────────────────────────────────────────
        name_selectors = [
            '[class*="name"]', '[class*="title"]',
            'td:nth-child(2)', 'td:nth-child(3)',
            'h3', 'h4', '.text-ellipsis',
        ]
        product.name = await self._extract_text(element, name_selectors)

        # ── 商品价格 ────────────────────────────────────────────────────
        price_selectors = [
            '[class*="price"]', '[class*="amount"]',
            'td:nth-child(4)', 'td:nth-child(5)',
        ]
        product.price = await self._extract_text(element, price_selectors)

        # ── 商品状态 ────────────────────────────────────────────────────
        status_selectors = [
            '[class*="status"]', '[class*="state"]',
            '[class*="tag"]',
        ]
        product.status = await self._extract_text(element, status_selectors)

        # ── 商品 ID ────────────────────────────────────────────────────
        # 尝试从链接、data 属性或页面文本中提取
        product.item_id = await self._extract_item_id(element)

        # ── 商品图片 URL ────────────────────────────────────────────────
        product.main_images = await self._extract_image_urls(element)

        if not product.name:
            return None

        return product

    async def _extract_text(self, element, selectors: List[str]) -> str:
        """从元素中提取文本"""
        for sel in selectors:
            try:
                target = await element.query_selector(sel)
                if target:
                    text = await target.inner_text()
                    text = text.strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    async def _extract_item_id(self, element) -> str:
        """提取商品 ID"""
        # 从链接中提取
        try:
            link = await element.query_selector('a[href*="goods"], a[href*="item"]')
            if link:
                href = await link.get_attribute("href")
                if href:
                    # 提取 URL 中的 ID
                    match = re.search(r'[?&]id=([^&]+)', href)
                    if match:
                        return match.group(1)
                    # 提取路径中的 ID
                    match = re.search(r'/(?:goods|item)/(\d+)', href)
                    if match:
                        return match.group(1)
        except Exception:
            logger.debug("Caught Exception, continuing")

        # 从 data 属性提取
        for attr in ["data-id", "data-item-id", "data-goods-id", "data-key"]:
            try:
                val = await element.get_attribute(attr)
                if val:
                    return val
            except Exception:
                continue

        # 从 checkbox value 提取
        try:
            checkbox = await element.query_selector('input[type="checkbox"]')
            if checkbox:
                val = await checkbox.get_attribute("value")
                if val:
                    return val
        except Exception:
            logger.debug("Caught Exception, continuing")

        # 用名称哈希作为兜底 ID
        name = await self._extract_text(element, ['[class*="name"]', '[class*="title"]'])
        if name:
            return hashlib.md5(name.encode()).hexdigest()[:12]

        return ""

    async def _extract_image_urls(self, element) -> List[str]:
        """提取商品图片 URL"""
        urls = []
        imgs = await element.query_selector_all('img')
        for img in imgs:
            src = await img.get_attribute("src")
            if not src:
                src = await img.get_attribute("data-src")
            if not src:
                src = await img.get_attribute("data-lazy-src")
            if src:
                # 补全相对 URL
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = urljoin(self.BASE_URL, src)
                # 过滤掉图标、占位图等
                if self._is_product_image(src) and src not in urls:
                    urls.append(src)
        return urls

    def _product_image_urls(self, product: Product) -> List[tuple[str, str]]:
        """Return de-duplicated image URLs, main images first, capped per product."""
        urls: List[tuple[str, str]] = []
        seen = set()
        for kind, source_urls in (
            ("main", product.main_images),
            ("detail", product.detail_images),
        ):
            for url in source_urls:
                if not url or url in seen:
                    continue
                seen.add(url)
                urls.append((kind, url))
                if len(urls) >= self.images_per_product:
                    return urls
        return urls

    @staticmethod
    def _is_product_image(url: str) -> bool:
        """判断是否为商品图片（排除图标、logo 等）"""
        # 排除明显的非商品图
        exclude_patterns = [
            "logo", "icon", "avatar", "emoji", "loading",
            "placeholder", "default", "empty", "arrow",
            "favicon", "badge",
        ]
        url_lower = url.lower()
        for pat in exclude_patterns:
            if pat in url_lower:
                return False

        # 图片尺寸通常较大，排除太小的
        # 有些 CDN URL 包含尺寸信息，如 @100w_100h
        size_match = re.search(r'@(\d+)w_(\d+)h', url)
        if size_match:
            w, h = int(size_match.group(1)), int(size_match.group(2))
            if w < 100 or h < 100:
                return False

        return True

    # ── 分页 ────────────────────────────────────────────────────────────

    async def _go_next_page(self) -> bool:
        """翻到下一页，返回是否有下一页"""
        # 尝试多种翻页按钮选择器
        next_selectors = [
            # antd 风格分页
            '.ant-pagination-next:not(.ant-pagination-disabled)',
            # element-ui 风格
            '.el-pagination .btn-next:not(.disabled)',
            # 通用分页
            '[class*="pagination"] [class*="next"]:not([class*="disabled"])',
            'button:has-text("下一页"):not([disabled])',
            'a:has-text("下一页"):not([class*="disabled"])',
            # 第三方分页组件
            '[class*="pager"] [class*="next"]',
        ]

        for selector in next_selectors:
            try:
                btn = await self.page.query_selector(selector)
                if btn:
                    is_visible = await btn.is_visible()
                    is_enabled = await btn.is_enabled()
                    if is_visible and is_enabled:
                        await btn.click()
                        await AntiDetect.human_like_delay(2.0, 4.0)
                        # 等待列表刷新
                        await self._wait_for_goods_list()
                        return True
            except Exception:
                continue

        # 尝试点击页码（当前页 + 1）
        try:
            current_page_el = await self.page.query_selector(
                '.ant-pagination-item-active, .el-pager .active, [class*="current"]'
            )
            if current_page_el:
                current_num = await current_page_el.inner_text()
                next_num = int(current_num.strip()) + 1
                next_page_btn = await self.page.query_selector(
                    f'.ant-pagination-item-{next_num}, '
                    f'.el-pager li:has-text("{next_num}"), '
                    f'[class*="page"]:has-text("{next_num}")'
                )
                if next_page_btn and await next_page_btn.is_visible():
                    await next_page_btn.click()
                    await AntiDetect.human_like_delay(2.0, 4.0)
                    await self._wait_for_goods_list()
                    return True
        except Exception:
            logger.debug("Caught Exception, continuing")

        return False

    # ── 商品详情采集（SKU、详情图） ────────────────────────────────────

    async def collect_product_detail(self, product: Product) -> Product:
        """
        采集单个商品的详情页信息（SKU、详情图等）

        需要先在商品列表页找到对应商品的链接并进入详情页。
        """
        if not product.item_id:
            return product

        # 尝试在当前列表页找到商品链接
        detail_url = await self._find_product_detail_url(product)
        if not detail_url:
            logger.warning("未找到商品详情链接: %s", product.name)
            return product

        try:
            await self._browser.goto(detail_url)
            await AntiDetect.human_like_delay(2.0, 4.0)

            # 采集详情图
            product.detail_images = await self._collect_detail_images()

            # 采集 SKU 信息
            product.skus = await self._collect_skus()

            # 返回列表页
            await self._browser.goto(self.GOODS_LIST_URL)
            await AntiDetect.human_like_delay(2.0, 3.0)

        except Exception as e:
            logger.error("采集商品详情出错 [%s]: %s", product.name, e)

        return product

    async def _find_product_detail_url(self, product: Product) -> Optional[str]:
        """在列表页找到商品的详情链接"""
        if product.item_id:
            # 尝试通过 ID 构造详情 URL
            return f"{self.BASE_URL}/ark/goods/detail/{product.item_id}"
        return None

    async def _collect_detail_images(self) -> List[str]:
        """采集详情页的图片"""
        urls = []
        selectors = [
            '[class*="detail"] img',
            '[class*="description"] img',
            '[class*="content"] img',
            '[class*="rich-text"] img',
            '.ql-editor img',
            '[class*="editor"] img',
        ]
        for sel in selectors:
            imgs = await self.page.query_selector_all(sel)
            for img in imgs:
                src = await img.get_attribute("src")
                if not src:
                    src = await img.get_attribute("data-src")
                if src:
                    if src.startswith("//"):
                        src = "https:" + src
                    elif src.startswith("/"):
                        src = urljoin(self.BASE_URL, src)
                    if src not in urls:
                        urls.append(src)
            if urls:
                break
        return urls

    async def _collect_skus(self) -> List[Dict[str, Any]]:
        """采集 SKU 信息"""
        skus = []
        try:
            # 尝试从页面中提取 SKU 表格数据
            sku_rows = await self.page.query_selector_all(
                '[class*="sku"] tr, [class*="spec"] tr, [class*="variant"] [class*="row"]'
            )
            for row in sku_rows:
                cells = await row.query_selector_all('td, [class*="cell"]')
                if len(cells) >= 2:
                    sku = {}
                    # 通常第一列是 SKU 名称/规格
                    name_text = await cells[0].inner_text()
                    sku["spec"] = name_text.strip()
                    # 第二列可能是价格
                    if len(cells) > 1:
                        price_text = await cells[1].inner_text()
                        sku["price"] = price_text.strip()
                    # 第三列可能是库存
                    if len(cells) > 2:
                        stock_text = await cells[2].inner_text()
                        sku["stock"] = stock_text.strip()
                    skus.append(sku)
        except Exception as e:
            logger.debug("采集 SKU 出错: %s", e)
        return skus

    # ── 图片下载 ────────────────────────────────────────────────────────

    async def download_all_images(
        self,
        products: List[Product],
        concurrency: int = 3,
    ) -> None:
        """
        下载所有商品的图片

        支持断点续传：已下载的图片会跳过。

        Args:
            products: 商品列表
            concurrency: 并发下载数（保留参数兼容性，实际串行下载）
        """
        os.makedirs(self.output_dir, exist_ok=True)
        self._load_progress()

        total = sum(len(self._product_image_urls(p)) for p in products)
        downloaded = 0
        skipped = 0

        logger.info("开始下载图片，共 %s 张，已有进度 %s 张", total, len(self._downloaded))

        # 使用浏览器 Context 下载（自动带登录态 Cookie）
        for product in products:
            product_dir = self._get_product_dir(product)
            os.makedirs(product_dir, exist_ok=True)

            image_urls = self._product_image_urls(product)
            product.local_images = []
            kind_counts = {"main": 0, "detail": 0}

            # 主图优先，详情图补足，每个产品最多 images_per_product 张
            for kind, url in image_urls:
                kind_counts[kind] += 1
                local_path = os.path.join(
                    product_dir,
                    f"{kind}_{kind_counts[kind]}{self._guess_ext(url)}",
                )
                if url in self._downloaded:
                    # 已下载，检查本地文件是否存在
                    if os.path.exists(local_path):
                        # 验证并转换图片（WEBP->JPG）
                        final_path = self._validate_and_convert_image(local_path)
                        if final_path:
                            product.local_images.append(final_path)
                            skipped += 1
                        else:
                            # 图片无效，重新下载
                            self._downloaded.discard(url)
                            logger.info("图片无效，重新下载: %s", url)
                            continue
                success = await self._download_image(url, local_path)
                if success:
                    # 验证并转换图片（WEBP->JPG）
                    logger.info("下载成功，验证图片: %s", url[:80])
                    final_path = self._validate_and_convert_image(local_path)
                    if final_path:
                        product.local_images.append(final_path)
                        self._downloaded.add(url)
                        self._save_progress()
                        downloaded += 1
                        logger.info("图片验证通过: %s -> %s", url[:50], final_path)
                    else:
                        logger.warning("下载的图片无效或太小: %s", url)
                else:
                    logger.warning("下载失败（_download_image返回False）: %s", url)
                await AntiDetect.human_like_delay(0.3, 1.0)

        logger.info("图片下载完成：下载 %s 张，跳过 %s 张", downloaded, skipped)

    async def _download_image(
        self,
        url: str,
        local_path: str,
        retries: int = 3,
    ) -> bool:
        """
        下载单张图片（带重试）
        使用浏览器 Context 发起请求（带完整登录态 Cookie）
        """
        for attempt in range(retries):
            try:
                # 用浏览器 Context 发起请求（自动带 Cookie）
                resp = await self._browser.context.request.get(
                    url,
                    headers={
                        "User-Agent": AntiDetect.random_user_agent(),
                        "Referer": self.BASE_URL,
                    },
                    timeout=30000,
                )
                if resp.status == 200:
                    data = await resp.body()
                    with open(local_path, "wb") as f:
                        f.write(data)
                    logger.debug("已下载: %s (%s bytes)", os.path.basename(local_path), len(data))
                    await resp.dispose()
                    return True
                else:
                    logger.warning("下载失败 (HTTP %s): %s", resp.status, url)
                    await resp.dispose()
            except Exception as e:
                logger.warning("下载出错 (尝试 %s/%s): %s", attempt+1, retries, e)
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)

        return False

    def _validate_and_convert_image(self, local_path: str) -> str:
        """
        验证图片文件是否有效，如果是 WEBP 则转换成 JPG
        返回最终的图片路径（可能已转换），如果无效则返回空字符串
        """
        if not os.path.exists(local_path):
            return ""
        
        # 检查文件大小（有效图片至少 10KB）
        file_size = os.path.getsize(local_path)
        if file_size < 10240:
            logger.warning("图片文件过小（%s bytes），删除: %s", file_size, local_path)
            try:
                os.remove(local_path)
            except Exception:
                pass
            return ""
        
        # 检查文件格式并转换 WEBP 为 JPG
        try:
            from PIL import Image
            # 验证文件是否完整
            img = Image.open(local_path)
            img.verify()
            
            # 如果是 WEBP，转换成 JPG
            if local_path.lower().endswith('.webp'):
                jpg_path = local_path.rsplit('.', 1)[0] + '.jpg'
                img = Image.open(local_path)  # verify() 后需要重新打开
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                img.save(jpg_path, 'JPEG', quality=95)
                logger.info("WEBP 转 JPG: %s -> %s", local_path, jpg_path)
                try:
                    os.remove(local_path)
                except Exception:
                    pass
                return jpg_path
            
            return local_path
        except Exception as e:
            logger.warning("图片验证失败，删除: %s (%s)", local_path, e)
            try:
                os.remove(local_path)
            except Exception:
                pass
            return ""

    def _get_product_dir(self, product: Product) -> str:
        """获取商品图片保存目录"""
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', product.name)[:50]
        dir_name = f"{product.item_id}_{safe_name}" if product.item_id else safe_name
        return os.path.join(self.output_dir, "images", dir_name)

    @staticmethod
    def _guess_ext(url: str) -> str:
        """根据 URL 猜测图片扩展名"""
        parsed = urlparse(url)
        path = parsed.path.lower()
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]:
            if path.endswith(ext):
                return ext
        # 检查查询参数中的格式信息
        if "format=png" in url or "type=png" in url:
            return ".png"
        if "format=webp" in url or "type=webp" in url:
            return ".webp"
        return ".jpg"  # 默认

    # ── 断点续传 ────────────────────────────────────────────────────────

    def _load_progress(self):
        """加载下载进度"""
        if os.path.exists(self._progress_file):
            try:
                with open(self._progress_file, "r") as f:
                    data = json.load(f)
                self._downloaded = set(data.get("downloaded", []))
                logger.debug("加载下载进度: %s 条", len(self._downloaded))
            except Exception:
                self._downloaded = set()

    def _save_progress(self):
        """保存下载进度"""
        try:
            os.makedirs(os.path.dirname(self._progress_file), exist_ok=True)
            with open(self._progress_file, "w") as f:
                json.dump({"downloaded": list(self._downloaded)}, f)
        except Exception:
            logger.debug("Caught Exception, continuing")

    # ── 数据导出 ────────────────────────────────────────────────────────

    def export_json(
        self,
        products: List[Product],
        filename: str = "products.json",
    ) -> str:
        """
        导出商品数据为 JSON 文件

        Args:
            products: 商品列表
            filename: 输出文件名

        Returns:
            导出文件路径
        """
        output_path = os.path.join(self.output_dir, filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        data = {
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(products),
            "products": [p.to_dict() for p in products],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("数据已导出: %s", output_path)
        return output_path

    def export_simple(
        self,
        products: List[Product],
        filename: str = "products_simple.json",
    ) -> str:
        """
        导出简化的商品数据（只包含标题和主图）

        Args:
            products: 商品列表
            filename: 输出文件名

        Returns:
            导出文件路径
        """
        output_path = os.path.join(self.output_dir, filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        simple_products = []
        for p in products:
            simple_products.append({
                "item_id": p.item_id,
                "title": p.name,
                "main_images": p.main_images[:self.images_per_product],
                "detail_images": p.detail_images[:self.images_per_product],
                "local_images": p.local_images[:self.images_per_product],
            })

        data = {
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(products),
            "products": simple_products,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("简化数据已导出: %s", output_path)
        return output_path

    # ── 调试辅助 ────────────────────────────────────────────────────────

    async def _debug_screenshot(self, name: str):
        """调试截图"""
        debug_dir = os.path.join(self.output_dir, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        path = os.path.join(debug_dir, f"{name}_{int(time.time())}.png")
        try:
            await self.page.screenshot(path=path, full_page=True)
            logger.debug("调试截图已保存: %s", path)
        except Exception:
            logger.debug("Caught Exception, continuing")

    async def debug_dump_page_structure(self) -> str:
        """
        导出当前页面的 DOM 结构（用于调试选择器）

        返回页面中所有 class 名和 tag 的概要信息。
        """
        try:
            structure = await self.page.evaluate("""
            () => {
                const result = [];
                const walk = (el, depth) => {
                    if (depth > 4) return;
                    const tag = el.tagName?.toLowerCase();
                    const cls = el.className && typeof el.className === 'string'
                        ? el.className.split(' ').filter(c => c).slice(0, 3).join('.')
                        : '';
                    const text = el.childNodes.length === 1 && el.childNodes[0].nodeType === 3
                        ? el.childNodes[0].textContent.trim().slice(0, 40)
                        : '';
                    const prefix = '  '.repeat(depth);
                    const desc = cls ? `${tag}.${cls}` : tag;
                    const info = text ? `${desc} → "${text}"` : desc;
                    if (info && info !== 'undefined') result.push(prefix + info);
                    for (const child of el.children || []) {
                        walk(child, depth + 1);
                    }
                };
                walk(document.body, 0);
                return result.slice(0, 200).join('\\n');
            }
            """)
            return structure
        except Exception as e:
            return f"导出失败: {e}"


# ── CLI 入口 ────────────────────────────────────────────────────────────────

async def main():
    """命令行入口"""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="千帆后台产品图采集器")
    parser.add_argument("--output", "-o", default=None, help="输出目录")
    parser.add_argument("--max-pages", "-p", type=int, default=0, help="最大采集页数（0=不限）")
    parser.add_argument(
        "--images-per-product",
        type=int,
        default=DEFAULT_IMAGES_PER_PRODUCT,
        help=f"每个商品最多下载图片数（默认 {DEFAULT_IMAGES_PER_PRODUCT}）",
    )
    parser.add_argument("--headless", action="store_true", help="无头模式（调试时不建议）")
    parser.add_argument("--debug-dom", action="store_true", help="仅导出页面 DOM 结构（调试用）")
    args = parser.parse_args()

    async with QianfanCollector(
        output_dir=args.output,
        headless=args.headless,
        images_per_product=args.images_per_product,
    ) as collector:
        # 登录
        if not await collector.ensure_login():
            logger.error("登录失败，退出")
            return

        # 调试模式：仅导出 DOM
        if args.debug_dom:
            dom = await collector.debug_dump_page_structure()
            logger.debug("Output: %s", dom)
            return

        # 采集商品
        products = await collector.collect_all_products(max_pages=args.max_pages)

        if not products:
            logger.warning("未采集到商品数据")
            # 导出 DOM 以便调试
            dom = await collector.debug_dump_page_structure()
            debug_path = os.path.join(collector.output_dir, "debug", "dom_structure.txt")
            os.makedirs(os.path.dirname(debug_path), exist_ok=True)
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(dom)
            logger.info("页面 DOM 结构已保存到: %s", debug_path)
            return

        logger.info("开始下载商品图片，每个商品最多 %s 张...", collector.images_per_product)
        await collector.download_all_images(products)

        # 导出简化数据（标题 + 最多 N 张本地图）
        output_path = collector.export_simple(products)
        logger.info("采集完成！数据文件: %s", output_path)
        logger.info("图片目录: %s", os.path.join(collector.output_dir, 'images'))


if __name__ == "__main__":
    asyncio.run(main())
