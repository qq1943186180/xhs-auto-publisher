"""
XHS Auto Publisher - Main Window
Kimi WebBridge 发布 + 持久化存储
"""
import sys
import json
import os
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject

from qfluentwidgets import FluentWindow, FluentIcon, InfoBar

from .pages.task_list_page import TaskListPage
from .pages.ai_generate_page import AIGeneratePage
from .pages.publish_page import PublishPage
from .pages.settings_page import SettingsPage
from .widgets.log_console import LogConsole
from .styles.theme import APP_BACKGROUND, BORDER, SURFACE, setup_theme

logger = logging.getLogger(__name__)

COLLECTED_DIR = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "collected")
PRODUCTS_JSON = os.path.join(COLLECTED_DIR, "products_simple.json")
CONFIG_JSON = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "config.json")
GENERATED_IMAGES_DIR = Path.home() / ".xhs-publisher" / "generated_images"
COLLECTED_IMAGES_PER_PRODUCT = 5


def _safe_dir_name(text: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text or "product").strip(" ._")
    return name[:48] or "product"


def _new_image_output_dir(product_name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = GENERATED_IMAGES_DIR / f"{stamp}_{_safe_dir_name(product_name)}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir)


def _reuse_or_create_image_output_dir(product_name: str, existing_images: list[str]) -> str:
    for image in existing_images or []:
        if image and os.path.exists(image):
            parent = Path(image).parent
            parent.mkdir(parents=True, exist_ok=True)
            return str(parent)
    return _new_image_output_dir(product_name)


def _images_per_product_config() -> int:
    try:
        if os.path.exists(CONFIG_JSON):
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                config = json.load(f)
            value = int(config.get("images_per_product", COLLECTED_IMAGES_PER_PRODUCT))
            return max(1, min(9, value))
    except Exception as e:
        logger.warning(f"Load images_per_product config failed: {e}")
    return COLLECTED_IMAGES_PER_PRODUCT


class AIBackend(QObject):
    """AI generation backend - 两轮生成：方向 → 文案"""
    finished = pyqtSignal(dict)
    direction_done = pyqtSignal(dict)  # 第一轮完成信号
    image_retry_done = pyqtSignal(dict)
    note_image_done = pyqtSignal(dict)

    def generate(self, product, style="种草"):
        def _run():
            try:
                from src.ai.api_key_manager import get_key_manager
                km = get_key_manager()

                product_name = product.get("title", "")
                desc = product_name
                local_imgs = product.get("local_images", [])

                errors = []
                has_llm_key = km.has_keys()

                # ========================================
                # 第一轮：方向生成
                # ========================================
                logger.info("第一轮：生成内容方向...")
                directions_data = []
                if has_llm_key:
                    try:
                        from src.ai.direction_generator import generate_directions
                        dir_result = generate_directions(
                            product_name=product_name,
                            description=desc,
                            style=style,
                        )
                        directions_data = [
                            {
                                "id": d.id,
                                "name": d.name,
                                "target_audience": d.target_audience,
                                "angle": d.angle,
                                "hook_type": d.hook_type,
                                "style_hint": d.style_hint,
                            }
                            for d in dir_result.directions
                        ]
                        logger.info(f"方向生成完成: {[d['name'] for d in directions_data]}")
                    except Exception as e:
                        errors.append(f"方向生成失败: {e}")
                        logger.warning(f"Direction generation failed: {e}")

                if not directions_data:
                    # 兜底方向
                    from src.ai.direction_generator import _FALLBACK_DIRECTIONS
                    directions_data = list(_FALLBACK_DIRECTIONS)

                # 通知 UI 第一轮完成
                self.direction_done.emit({"directions": directions_data})

                # ========================================
                # 第二轮：每个方向生成 3 篇文案
                # ========================================
                all_posts = []
                for dir_data in directions_data:
                    dir_name = dir_data["name"]
                    logger.info(f"第二轮：方向「{dir_name}」生成 3 篇文案...")

                    if has_llm_key:
                        try:
                            from src.ai.content_generator import generate_direction_content
                            dir_content = generate_direction_content(
                                product_name=product_name,
                                description=desc,
                                price="未知",
                                selling_points="",
                                direction=dir_data,
                                style=style,
                            )
                            for post in dir_content.posts:
                                all_posts.append({
                                    "direction_id": dir_data["id"],
                                    "direction_name": dir_name,
                                    "hook_style": post.hook_style,
                                    "title": post.title,
                                    "content": post.content,
                                    "tags": " ".join(post.tags) if post.tags else "",
                                })
                        except Exception as e:
                            errors.append(f"方向「{dir_name}」文案生成失败: {e}")
                            logger.warning(f"Content gen for direction {dir_name} failed: {e}")

                    # 如果该方向没有生成任何帖子，用模板兜底
                    dir_posts = [p for p in all_posts if p["direction_id"] == dir_data["id"]]
                    if not dir_posts:
                        from src.ai.content_generator import _generate_template_posts
                        template_posts = _generate_template_posts(
                            product_name,
                            desc,
                            dir_data,
                            style=style,
                        )
                        for tp in template_posts:
                            all_posts.append({
                                "direction_id": dir_data["id"],
                                "direction_name": dir_name,
                                "hook_style": tp.hook_style,
                                "title": tp.title,
                                "content": tp.content,
                                "tags": " ".join(tp.tags) if tp.tags else "",
                            })

                # 取第一篇的标题作为默认展示
                best_title = all_posts[0]["title"] if all_posts else product_name

                # 生成图片（3 张）
                images = []
                image_results = []
                from src.ai.image_generator import check_kimi_health
                if not check_kimi_health():
                    errors.append("Kimi WebBridge 不可用，请确保浏览器扩展已连接")
                else:
                    try:
                        from src.ai.image_generator import generate_images
                        output_dir = _new_image_output_dir(product_name)
                        product_img = None
                        if local_imgs and os.path.exists(local_imgs[0]):
                            product_img = local_imgs[0]
                        img_result = generate_images(
                            product_name=product_name,
                            output_dir=output_dir,
                            product_image_path=product_img,
                            count=3,
                        )
                        images = img_result.images
                        image_results = img_result.results
                        if not images:
                            errors.append("图片生成失败，请检查 ChatGPT 登录状态")
                        elif len(images) < 3:
                            errors.append(f"图片生成不完整：已生成 {len(images)}/3 张，可点击缺失图片重试")
                    except Exception as e:
                        errors.append(f"图片生成失败: {e}")
                        logger.warning(f"Image generation failed: {e}")
                        image_results = []

                result = {
                    "title": best_title,
                    "content": all_posts[0]["content"] if all_posts else "",
                    "tags": all_posts[0]["tags"] if all_posts else "",
                    "images": images,
                    "image_results": image_results,
                    "product_name": product_name,
                    "posts": all_posts,       # 全部 9 篇
                    "directions": directions_data,
                }
                if errors:
                    result["warnings"] = errors

                self.finished.emit(result)
            except Exception as e:
                logger.error(f"AI generation failed: {e}")
                self.finished.emit({
                    "title": f"[Error] {e}",
                    "content": "",
                    "tags": "",
                    "images": [],
                    "product_name": product.get("title", ""),
                    "posts": [],
                    "directions": [],
                    "errors": [str(e)],
                })

        threading.Thread(target=_run, daemon=True).start()

    def retry_images(self, product, style_indices: list[int], existing_images: list[str]):
        def _run():
            product_name = product.get("title", "")
            local_imgs = product.get("local_images", [])
            errors = []
            image_results = []
            images = []
            try:
                from src.ai.image_generator import check_kimi_health, generate_images
                if not check_kimi_health():
                    errors.append("Kimi WebBridge 不可用，请确保浏览器扩展已连接")
                else:
                    product_img = None
                    if local_imgs and os.path.exists(local_imgs[0]):
                        product_img = local_imgs[0]
                    output_dir = _reuse_or_create_image_output_dir(product_name, existing_images)
                    img_result = generate_images(
                        product_name=product_name,
                        output_dir=output_dir,
                        product_image_path=product_img,
                        count=3,
                        style_indices=style_indices,
                    )
                    images = img_result.images
                    image_results = img_result.results
                    if not images:
                        errors.append("缺失图片重试失败，请检查 ChatGPT 登录状态")
            except Exception as e:
                errors.append(f"缺失图片重试失败: {e}")
                logger.warning(f"Image retry failed: {e}")

            seen = {
                item.get("index")
                for item in image_results
                if isinstance(item, dict)
            }
            for index in style_indices:
                if index not in seen:
                    image_results.append({
                        "index": index,
                        "status": "failed",
                        "path": "",
                        "error": "；".join(errors) if errors else "生成失败或超时，请重试",
                    })

            self.image_retry_done.emit({
                "images": images,
                "image_results": image_results,
                "warnings": errors,
            })

        threading.Thread(target=_run, daemon=True).start()

    def generate_note_images(self, item: dict, product: dict | None = None):
        def _run():
            note_id = item.get("id")
            product_name = (
                (product or {}).get("title")
                or item.get("product_name")
                or item.get("title")
                or "商品"
            )
            existing_images = [
                path for path in item.get("images", [])
                if path and os.path.exists(path)
            ]
            errors = []
            image_results = []
            images = []

            try:
                from src.ai.image_generator import check_kimi_health, generate_images
                if not check_kimi_health():
                    errors.append("Kimi WebBridge 不可用，请确保浏览器扩展已连接")
                else:
                    local_imgs = (product or {}).get("local_images", [])
                    product_img = None
                    if local_imgs and os.path.exists(local_imgs[0]):
                        product_img = local_imgs[0]
                    elif existing_images:
                        product_img = existing_images[0]
                    else:
                        errors.append("未找到采集产品图，将使用文字提示词直接生图")

                    base_prompt = item.get("image_prompt") or (
                        f"请为 {product_name} 生成适合小红书种草笔记的真实商品图片。"
                    )
                    prompt_overrides = [
                        base_prompt + "\n风格补充：博主真实分享图，日常手持或桌面场景，温柔自然光，真实随拍质感。",
                        base_prompt + "\n风格补充：纯白简约商品图，干净背景，主体清晰，适合做首图，少道具。",
                        base_prompt + "\n风格补充：生活氛围场景图，有真实使用环境和高级感，但商品仍是视觉主体。",
                    ]

                    if len(existing_images) < 3:
                        style_indices = list(range(len(existing_images), 3))
                    else:
                        style_indices = [0, 1, 2]

                    output_dir = _new_image_output_dir(product_name)
                    img_result = generate_images(
                        product_name=product_name,
                        output_dir=output_dir,
                        product_image_path=product_img,
                        count=3,
                        style_indices=style_indices,
                        prompt_overrides=prompt_overrides,
                    )
                    images = img_result.images
                    image_results = img_result.results
                    if not images:
                        errors.append("直接生成图片失败，请检查 ChatGPT 登录状态")
            except Exception as e:
                errors.append(f"直接生成图片失败: {e}")
                logger.warning(f"Note image generation failed: {e}")

            all_images = existing_images + images
            self.note_image_done.emit({
                "note_id": note_id,
                "product_name": product_name,
                "images": images,
                "all_images": all_images,
                "image_results": image_results,
                "warnings": errors,
            })

        threading.Thread(target=_run, daemon=True).start()


class MainWindow(FluentWindow):
    """Main Window"""

    api_check_done = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("小红书自动发布系统")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        setup_theme()
        if hasattr(self, "setMicaEffectEnabled"):
            self.setMicaEffectEnabled(False)

        # Pages
        self.task_list_page = TaskListPage(self)
        self.task_list_page.setObjectName("task_list")
        self.ai_generate_page = AIGeneratePage(self)
        self.ai_generate_page.setObjectName("ai_generate")
        self.publish_page = PublishPage(self)
        self.publish_page.setObjectName("publish")
        self.settings_page = SettingsPage(self)
        self.settings_page.setObjectName("settings")
        self.log_console = LogConsole(self)
        self.log_console.hide()
        for page in (
            self.task_list_page,
            self.ai_generate_page,
            self.publish_page,
            self.settings_page,
        ):
            page.setStyleSheet(f"QWidget#{page.objectName()} {{ background: {APP_BACKGROUND}; }}")

        # AI backend
        self.ai_backend = AIBackend()
        self.ai_backend.finished.connect(self._on_ai_done)
        self.ai_backend.image_retry_done.connect(self._on_image_retry_done)
        self.ai_backend.note_image_done.connect(self._on_note_image_done)
        self.api_check_done.connect(self._show_api_check_warnings)

        # Navigation (FluentIcon.ROBOT may not exist in some versions)
        try:
            robot_icon = FluentIcon.ROBOT
        except AttributeError:
            robot_icon = FluentIcon.SEARCH
        self.addSubInterface(self.task_list_page, icon=FluentIcon.HOME, text="任务列表")
        self.addSubInterface(self.ai_generate_page, icon=robot_icon, text="AI 生成")
        self.addSubInterface(self.publish_page, icon=FluentIcon.SEND, text="发布管理")
        self.addSubInterface(self.settings_page, icon=FluentIcon.SETTING, text="设置")
        self._setup_window_chrome()

        # Logging
        handler = self.log_console.get_handler(logging.DEBUG)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.DEBUG)

        # Connect signals
        self.task_list_page.generate_requested.connect(self._on_generate_requested)
        self.task_list_page.collect_done.connect(self._load_collected_products)
        self.ai_generate_page.generate_clicked.connect(self._on_generate_from_ai_page)
        self.ai_generate_page.retry_images_clicked.connect(self._on_retry_images_requested)
        self.ai_generate_page.save_clicked.connect(self._on_save_current_draft)
        self.ai_generate_page.publish_clicked.connect(self._on_publish)
        self.publish_page.publish_requested.connect(self._do_publish)
        self.publish_page.direct_image_requested.connect(self._on_direct_note_image_requested)

        # Load data on start
        QTimer.singleShot(500, self._load_collected_products)
        QTimer.singleShot(600, self._load_saved_notes)
        QTimer.singleShot(700, self.settings_page.load_settings)
        QTimer.singleShot(1000, self._check_api_keys)

    def _setup_window_chrome(self):
        self.setStyleSheet(f"background: {APP_BACKGROUND};")
        if hasattr(self, "titleBar"):
            self.titleBar.setAttribute(Qt.WA_StyledBackground, True)
            self.titleBar.setStyleSheet(
                f"background: {SURFACE}; border-bottom: 1px solid {BORDER};"
            )
            self.titleBar.raise_()
        if hasattr(self, "navigationInterface"):
            self.navigationInterface.setAttribute(Qt.WA_StyledBackground, True)
            self.navigationInterface.setStyleSheet(
                f"background: {SURFACE}; border-right: 1px solid {BORDER};"
            )

    # ============================================================
    # 数据加载
    # ============================================================

    def _check_api_keys(self):
        """Check if API keys are configured, warn if not"""
        def _run():
            warnings = []
            try:
                from src.ai.api_key_manager import get_key_manager
                km = get_key_manager()
                if not km.has_keys():
                    warnings.append("LLM Key 未配置（标题/文案将使用模板）")
            except Exception as e:
                logger.warning(f"API key check failed: {e}")

            try:
                from src.ai.image_generator import check_kimi_health
                if not check_kimi_health():
                    warnings.append("Kimi WebBridge 未连接（无法生图，需启动浏览器扩展）")
            except Exception as e:
                logger.warning(f"Kimi health check failed: {e}")
                warnings.append("Kimi WebBridge 检查失败（无法确认生图能力）")

            self.api_check_done.emit(warnings)

        threading.Thread(target=_run, daemon=True).start()

    def _show_api_check_warnings(self, warnings: list):
        if warnings:
            InfoBar.warning(
                "系统检查",
                "；".join(warnings),
                duration=8000,
                parent=self,
            )

    def _load_collected_products(self):
        """Load products from collected JSON"""
        if not os.path.exists(PRODUCTS_JSON):
            return
        try:
            with open(PRODUCTS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            products = []
            image_limit = _images_per_product_config()
            for p in data.get("products", []):
                products.append({
                    "title": p.get("title", ""),
                    "local_images": p.get("local_images", [])[:image_limit],
                    "main_images": p.get("main_images", [])[:image_limit],
                    "detail_images": p.get("detail_images", [])[:image_limit],
                    "status": "pending",
                })
            self.task_list_page.load_products(products)
            logger.info(f"Loaded {len(products)} products")
        except Exception as e:
            logger.error(f"Failed to load products: {e}")

    def _load_saved_notes(self):
        """Load saved generated notes into publish page"""
        try:
            from src.database.generated_store import get_all_notes
            notes = get_all_notes()
            items = []
            for n in notes:
                status_text = {
                    "draft": "草稿",
                    "pending": "待发布",
                    "published": "已发布",
                    "failed": "发布失败",
                }.get(n.get("status", "draft"), n.get("status", ""))
                items.append({
                    "id": n.get("id"),
                    "title": n.get("title", ""),
                    "content": n.get("content", ""),
                    "tags": n.get("tags", ""),
                    "images": n.get("images", []),
                    "image_count": f"{len(n.get('images', []))}张",
                    "status": status_text,
                    "product_name": n.get("product_name", ""),
                    "created_at": n.get("created_at", ""),
                    "published_at": n.get("published_at", ""),
                    "error": n.get("error", ""),
                    "variants": n.get("variants", []),
                    "selected_variant_index": n.get("selected_variant_index", 0),
                })
            self.publish_page.load_items(items)
            logger.info(f"Loaded {len(notes)} saved notes")
        except Exception as e:
            logger.error(f"Failed to load saved notes: {e}")

    def _find_collected_product_for_note(self, item: dict) -> dict | None:
        """Find a collected product that can provide the real product image."""
        if not os.path.exists(PRODUCTS_JSON):
            return None
        try:
            with open(PRODUCTS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"Load collected products for note image failed: {e}")
            return None

        target = (item.get("product_name") or item.get("title") or "").strip()
        if not target:
            return None

        def normalize(value: str) -> str:
            return re.sub(r"\s+", "", value or "")

        target_norm = normalize(target)
        fallback = None
        image_limit = _images_per_product_config()
        for p in data.get("products", []):
            title = p.get("title", "")
            title_norm = normalize(title)
            product = {
                "title": title,
                "local_images": p.get("local_images", [])[:image_limit],
                "main_images": p.get("main_images", [])[:image_limit],
                "detail_images": p.get("detail_images", [])[:image_limit],
                "status": "pending",
            }
            if title_norm == target_norm:
                return product
            if title_norm and (title_norm in target_norm or target_norm in title_norm):
                fallback = product

        return fallback

    # ============================================================
    # AI 生成
    # ============================================================

    def _on_generate_requested(self, products):
        """Handle generate request from task list"""
        if not products:
            return
        product = products[0]
        self.ai_generate_page.set_product(product)
        self.switchTo(self.ai_generate_page)

        style = self.ai_generate_page.style_combo.currentText()
        self.ai_generate_page.set_generating(True)
        self.ai_backend.generate(product, style)

    def _on_generate_from_ai_page(self, data):
        product = data.get("product") if isinstance(data, dict) else None
        if not product:
            InfoBar.warning("提示", "请先从任务列表选择产品", parent=self.ai_generate_page)
            return
        self.ai_generate_page.set_product(product)
        self.ai_generate_page.set_generating(True)
        self.ai_backend.generate(product, data.get("style", "种草推荐"))

    def _on_ai_done(self, result):
        """AI generation finished - save to store"""
        product_name = result.get("product_name", "")
        warnings = result.get("warnings", [])
        errors = result.get("errors", [])
        posts = result.get("posts", [])
        images = result.get("images", [])
        image_results = result.get("image_results", [])
        directions = result.get("directions", [])

        # Display on AI page (show first post by default)
        first_title = posts[0]["title"] if posts else result.get("title", "")
        first_content = posts[0]["content"] if posts else result.get("content", "")
        first_tags = posts[0]["tags"] if posts else result.get("tags", "")

        self.ai_generate_page.set_content(first_title, first_content, first_tags)
        if image_results:
            self.ai_generate_page.set_image_results(image_results)
        else:
            self.ai_generate_page.set_images(images)
        self.ai_generate_page.set_posts(posts, directions)
        self.ai_generate_page.set_generating(False)

        # Show warnings/errors to user
        if errors:
            msg = "\n".join(errors)
            InfoBar.error("生成出错", msg, duration=8000, parent=self.ai_generate_page)
        elif warnings:
            msg = "\n".join(warnings)
            InfoBar.warning("部分完成", msg, duration=6000, parent=self.ai_generate_page)
        elif posts:
            InfoBar.success(
                "生成完成",
                f"{len(directions)} 个方向 × 3 篇 = {len(posts)} 篇文案 + {len(images)} 张图片",
                parent=self.ai_generate_page,
            )
        else:
            InfoBar.success("生成完成", "标题+文案已生成（无图片）", parent=self.ai_generate_page)

        # Save one draft record for the generation. The 9 posts are alternatives
        # inside the AI page, not 9 separate publish queue items.
        try:
            from src.database.generated_store import save_note
            note_ids = []
            if posts:
                post = posts[0]
                note = save_note(
                    title=post.get("title", ""),
                    content=post.get("content", ""),
                    tags=post.get("tags", ""),
                    images=images,  # 共享图片
                    product_name=product_name,
                    status="draft",
                    direction_id=post.get("direction_id", ""),
                    direction_name=post.get("direction_name", ""),
                    variants=posts,
                    selected_variant_index=0,
                )
                note_ids.append(note.get("id"))
            self.ai_generate_page.set_saved_note_ids(note_ids)
            if note_ids:
                logger.info(f"Saved 1 draft note for {product_name}; {len(posts)} versions kept in AI page")
        except Exception as e:
            logger.error(f"Save note failed: {e}")

        # Reload publish page
        self._load_saved_notes()

    def _on_retry_images_requested(self, indices):
        product = self.ai_generate_page._product
        if not product:
            InfoBar.warning("提示", "请先选择产品", parent=self.ai_generate_page)
            return
        cleaned_indices = []
        for value in indices:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= index < 3 and index not in cleaned_indices:
                cleaned_indices.append(index)
        indices = cleaned_indices
        if not indices:
            return
        existing_images = self.ai_generate_page.get_generated_images()
        self.ai_generate_page.set_image_slots_pending(indices)
        InfoBar.info("重试图片", f"正在补生成 {len(indices)} 张图片...", duration=3000, parent=self.ai_generate_page)
        self.ai_backend.retry_images(product, indices, existing_images)

    def _on_image_retry_done(self, result):
        image_results = result.get("image_results", [])
        warnings = result.get("warnings", [])
        self.ai_generate_page.update_image_results(image_results)
        images = self.ai_generate_page.get_generated_images()

        try:
            from src.database.generated_store import update_note_images
            for note_id in self.ai_generate_page.get_saved_note_ids():
                update_note_images(note_id, images)
        except Exception as e:
            logger.error(f"Update note images failed: {e}")

        self._load_saved_notes()
        if warnings:
            InfoBar.warning("图片未补齐", "\n".join(warnings), duration=6000, parent=self.ai_generate_page)
        elif self.ai_generate_page.get_missing_image_indices():
            InfoBar.warning("图片未补齐", "仍有图片生成失败，可继续重试", duration=5000, parent=self.ai_generate_page)
        else:
            InfoBar.success("图片已补齐", "3 张图片都已生成", parent=self.ai_generate_page)

    def _on_direct_note_image_requested(self, item: dict):
        note_id = item.get("id")
        if not note_id:
            InfoBar.warning("无法生成", "这条记录没有笔记 ID", parent=self.publish_page)
            return

        product = self._find_collected_product_for_note(item)
        if product:
            logger.info(f"Found product image for note id={note_id}: {product.get('title', '')[:30]}")
        else:
            logger.info(f"No collected product matched for note id={note_id}, using prompt-only image generation")

        InfoBar.info(
            "直接生成图片",
            "正在调用 ChatGPT/Kimi 为这条笔记生成图片...",
            duration=5000,
            parent=self.publish_page,
        )
        self.ai_backend.generate_note_images(item, product)

    def _on_note_image_done(self, result: dict):
        note_id = result.get("note_id")
        new_images = result.get("images", [])
        all_images = result.get("all_images", [])
        warnings = result.get("warnings", [])

        if new_images and note_id:
            try:
                from src.database.generated_store import update_note_images
                update_note_images(note_id, all_images)
            except Exception as e:
                logger.error(f"Update note direct images failed: {e}")
                InfoBar.error("保存失败", str(e), parent=self.publish_page)
                return

        self._load_saved_notes()

        if new_images:
            InfoBar.success(
                "图片已生成",
                f"已生成 {len(new_images)} 张，并写回这条笔记",
                duration=6000,
                parent=self.publish_page,
            )
            if warnings:
                InfoBar.warning("生成提示", "；".join(warnings), duration=6000, parent=self.publish_page)
        else:
            message = "；".join(warnings) if warnings else "没有生成可用图片"
            InfoBar.warning("直接生成失败", message, duration=8000, parent=self.publish_page)

    # ============================================================
    # 发布
    # ============================================================

    def _on_save_current_draft(self, data):
        """Save/update the selected version as the single draft for this generation."""
        title = data.get("title", "")
        content = data.get("content", "")
        tags = data.get("tags", "")
        images = data.get("images", [])
        product_name = data.get("product_name", "")
        note_id = data.get("note_id")

        if not title or not content:
            InfoBar.warning("提示", "请先生成内容再保存", parent=self.ai_generate_page)
            return

        try:
            from src.database.generated_store import save_note, update_note
            if note_id:
                update_note(
                    note_id,
                    title=title,
                    content=content,
                    tags=tags,
                    images=images,
                    product_name=product_name,
                    status="draft",
                    direction_id=data.get("direction_id", ""),
                    direction_name=data.get("direction_name", ""),
                    variants=data.get("variants"),
                    selected_variant_index=data.get("selected_variant_index"),
                )
                logger.info(f"Updated draft note id={note_id}")
            else:
                note = save_note(
                    title=title,
                    content=content,
                    tags=tags,
                    images=images,
                    product_name=product_name,
                    status="draft",
                    direction_id=data.get("direction_id", ""),
                    direction_name=data.get("direction_name", ""),
                    variants=data.get("variants"),
                    selected_variant_index=data.get("selected_variant_index", 0),
                )
                self.ai_generate_page.set_saved_note_ids([note.get("id")])
                logger.info(f"Saved current draft note id={note.get('id')}")
            self._load_saved_notes()
        except Exception as e:
            logger.error(f"Save current draft failed: {e}")
            InfoBar.error("保存失败", str(e), parent=self.ai_generate_page)

    def _on_publish(self, data):
        """Save and add to publish queue"""
        title = data.get("title", "")
        content = data.get("content", "")
        tags = data.get("tags", "")
        images = data.get("images", [])
        product_name = data.get("product_name", "")
        note_id = data.get("note_id")

        # Check if this note already exists in store (from AI generation)
        # If so, just update status to pending instead of creating duplicate
        try:
            from src.database.generated_store import (
                get_all_notes,
                save_note,
                update_note,
            )
            if note_id:
                update_note(
                    note_id,
                    title=title,
                    content=content,
                    tags=tags,
                    images=images,
                    product_name=product_name,
                    status="pending",
                    direction_id=data.get("direction_id", ""),
                    direction_name=data.get("direction_name", ""),
                    variants=data.get("variants"),
                    selected_variant_index=data.get("selected_variant_index"),
                )
                logger.info(f"Updated current note id={note_id} to pending")
            else:
                existing_notes = get_all_notes()
                matched = None
                for n in existing_notes:
                    if n.get("title") == title and n.get("content") == content:
                        matched = n
                        break

                if matched:
                    update_note(
                        matched["id"],
                        images=images,
                        status="pending",
                        variants=data.get("variants"),
                        selected_variant_index=data.get("selected_variant_index"),
                    )
                    logger.info(f"Updated existing note id={matched['id']} to pending")
                else:
                    note = save_note(
                        title=title,
                        content=content,
                        tags=tags,
                        images=images,
                        product_name=product_name,
                        status="pending",
                        direction_id=data.get("direction_id", ""),
                        direction_name=data.get("direction_name", ""),
                        variants=data.get("variants"),
                        selected_variant_index=data.get("selected_variant_index", 0),
                    )
                    self.ai_generate_page.set_saved_note_ids([note.get("id")])
        except Exception as e:
            logger.error(f"Save failed: {e}")

        # Reload publish page
        self._load_saved_notes()
        InfoBar.success("加入队列", f"「{title[:20]}」已加入发布队列", parent=self)
        self.switchTo(self.publish_page)

    def _do_publish(self, items):
        """Publish via CLI subprocess"""
        if not items:
            InfoBar.warning("提示", "没有要发布的笔记", parent=self)
            return

        InfoBar.info("开始发布", f"正在发布 {len(items)} 个笔记...", parent=self)

        def _publish_thread():
            try:
                import subprocess
                from src.database.generated_store import update_note_status

                cli_py = os.path.join(os.path.dirname(__file__), "..", "..", "cli.py")

                for i, item in enumerate(items):
                    title = item.get("title", "")
                    content = item.get("content", "")
                    tags = item.get("tags", "")
                    images = item.get("images", [])
                    note_id = item.get("id")

                    logger.info(f"发布 {i+1}/{len(items)}: {title[:30]}")

                    # Write temp files
                    tmp_dir = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "_publish_tmp")
                    os.makedirs(tmp_dir, exist_ok=True)

                    title_file = os.path.join(tmp_dir, "title.txt")
                    content_file = os.path.join(tmp_dir, "content.txt")
                    with open(title_file, "w", encoding="utf-8") as f:
                        f.write(title)
                    with open(content_file, "w", encoding="utf-8") as f:
                        f.write(content)

                    # Build command
                    cli_abs = os.path.abspath(cli_py)
                    cmd = [sys.executable, cli_abs, "publish",
                           "--title-file", title_file,
                           "--content-file", content_file]
                    valid_images = [img for img in images if os.path.exists(img)]
                    if valid_images:
                        cmd.append("--images")
                        cmd.extend(valid_images)
                    if tags:
                        cmd.extend(["--tags", tags])

                    # Run CLI
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=300,
                        encoding="utf-8", errors="replace",
                    )

                    # Parse JSON output
                    parsed = None
                    for line in result.stdout.strip().splitlines():
                        line = line.strip()
                        if line.startswith("{"):
                            try:
                                parsed = json.loads(line)
                            except:
                                continue

                    if parsed and parsed.get("success"):
                        logger.info(f"发布成功: {title[:30]}")
                        item["status"] = "已发布"
                        if note_id:
                            update_note_status(note_id, "published")
                    else:
                        error = (parsed or {}).get("message") or result.stderr[-200:] or "未知错误"
                        logger.error(f"发布失败: {error}")
                        item["status"] = "失败"
                        if note_id:
                            update_note_status(note_id, "failed", error=error)

                QTimer.singleShot(0, self._load_saved_notes)

            except subprocess.TimeoutExpired:
                logger.error("发布超时")
            except Exception as e:
                logger.error(f"发布异常: {e}")

        threading.Thread(target=_publish_thread, daemon=True).start()


def main():
    """Entry point"""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    app.setApplicationName("xhs-auto-publisher")
    app.setApplicationVersion("1.0.0")

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
