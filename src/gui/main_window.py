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
from PyQt5.QtWidgets import (
    QApplication, QMessageBox, QSystemTrayIcon, QMenu, QAction,
    QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QHBoxLayout,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QEvent
from PyQt5.QtGui import QCloseEvent

from qfluentwidgets import FluentWindow, FluentIcon, InfoBar

from .pages.task_list_page import TaskListPage
from .pages.ai_generate_page import AIGeneratePage
from .pages.publish_page import PublishPage
from .pages.settings_page import SettingsPage
from .pages.history_page import HistoryPage
from .pages.hot_topics_page import HotTopicsPage
from .pages.url_extract_page import URLExtractPage
from .pages.search_page import SearchPage
from .widgets.log_console import LogConsole
from .styles.theme import APP_BACKGROUND, BORDER, SURFACE, setup_theme
from .utils import PAGE_MARGINS

from src.services.ai_backend import (
    AIBackend,
    COLLECTED_DIR,
    PRODUCTS_JSON,
    CONFIG_JSON,
    GENERATED_IMAGES_DIR,
    COLLECTED_IMAGES_PER_PRODUCT,
    _images_per_product_config,
    _new_image_output_dir,
)
from src.utils.error_messages import explain_error, summarize_errors
from src.utils.logger import get_logger

logger = get_logger("gui.main_window")


class MainWindow(FluentWindow):
    """Main Window"""

    api_check_done = pyqtSignal(list)
    publish_progress = pyqtSignal(int, int)
    publish_summary = pyqtSignal(str, int, int)
    publish_error = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("小红书自动发布系统")
        self.setMinimumSize(1024, 680)
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
        self.history_page = HistoryPage(self)
        self.history_page.setObjectName("history")
        self.hot_topics_page = HotTopicsPage(self)
        self.hot_topics_page.setObjectName("hot_topics")
        self.url_extract_page = URLExtractPage(self)
        self.url_extract_page.setObjectName("url_extract")
        self.search_page = SearchPage(self)
        self.search_page.setObjectName("search")
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

        # AI backend (service layer)
        self.ai_backend = AIBackend()
        self.ai_backend.finished.connect(self._on_ai_done, Qt.QueuedConnection)
        self.ai_backend.images_ready.connect(self._on_images_ready, Qt.QueuedConnection)
        self.ai_backend.image_retry_done.connect(self._on_image_retry_done, Qt.QueuedConnection)
        self.ai_backend.note_image_done.connect(self._on_note_image_done, Qt.QueuedConnection)
        self.ai_backend.direction_done.connect(self._on_directions_ready, Qt.QueuedConnection)
        self.ai_backend.step_changed.connect(self.ai_generate_page.set_step, Qt.QueuedConnection)
        self.ai_backend.content_regenerated.connect(self._on_content_regenerated, Qt.QueuedConnection)
        self.ai_backend.images_regenerated.connect(self._on_images_regenerated, Qt.QueuedConnection)
        self.api_check_done.connect(self._show_api_check_warnings, Qt.QueuedConnection)
        self.publish_progress.connect(self.publish_page.set_progress, Qt.QueuedConnection)
        self.publish_summary.connect(self._show_publish_summary, Qt.QueuedConnection)
        self.publish_error.connect(self._show_publish_error, Qt.QueuedConnection)

        # State tracking for close-event protection, batch queue, and early images
        self._is_generating = False
        self._is_publishing = False
        self._generate_queue = []
        self._generate_total = 0
        self._images_shown_early = False  # True when images_ready already displayed
        self._notifications = []

        # Navigation (FluentIcon.ROBOT may not exist in some versions)
        try:
            robot_icon = FluentIcon.ROBOT
        except AttributeError:
            robot_icon = FluentIcon.SEARCH
        # 使用安全的图标
        try:
            fire_icon = FluentIcon.STAR
        except AttributeError:
            fire_icon = FluentIcon.SEARCH
        try:
            link_icon = FluentIcon.ACCEPT
        except AttributeError:
            link_icon = FluentIcon.SEARCH
        self.addSubInterface(self.task_list_page, icon=FluentIcon.HOME, text="任务列表")
        self.addSubInterface(self.ai_generate_page, icon=robot_icon, text="AI 生成")
        self.addSubInterface(self.hot_topics_page, icon=fire_icon, text="热点推荐")
        self.addSubInterface(self.url_extract_page, icon=link_icon, text="URL 提取")
        self.addSubInterface(self.search_page, icon=FluentIcon.SEARCH, text="搜索资料")
        self.addSubInterface(self.publish_page, icon=FluentIcon.SEND, text="发布管理")
        self.addSubInterface(self.history_page, icon=FluentIcon.HISTORY, text="生成历史")
        self.addSubInterface(self.settings_page, icon=FluentIcon.SETTING, text="设置")
        self._setup_window_chrome()

        # Log console toggle button in title bar
        from qfluentwidgets import ToolButton
        self._log_toggle_btn = ToolButton(FluentIcon.DEVELOPER_TOOLS, self.titleBar)
        self._log_toggle_btn.setToolTip("显示/隐藏日志控制台")
        self._log_toggle_btn.setFixedSize(36, 36)
        if hasattr(self.titleBar, "hBoxLayout"):
            self.titleBar.hBoxLayout.addWidget(self._log_toggle_btn)
        elif hasattr(self.titleBar, "layout"):
            self.titleBar.layout().addWidget(self._log_toggle_btn)
        self._log_toggle_btn.clicked.connect(self._toggle_log_console)

        self._notification_btn = ToolButton(FluentIcon.MESSAGE, self.titleBar)
        self._notification_btn.setToolTip("通知中心")
        self._notification_btn.setFixedSize(36, 36)
        if hasattr(self.titleBar, "hBoxLayout"):
            self.titleBar.hBoxLayout.addWidget(self._notification_btn)
        elif hasattr(self.titleBar, "layout"):
            self.titleBar.layout().addWidget(self._notification_btn)
        self._notification_btn.clicked.connect(self._open_notification_center)

        # System tray icon
        self._tray_icon = None
        self._setup_tray_icon()

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
        self.ai_generate_page.prompt_edit_requested.connect(self._on_prompt_edit_requested)
        self.ai_generate_page.regenerate_content_clicked.connect(self._on_regenerate_content_requested)
        self.ai_generate_page.regenerate_images_clicked.connect(self._on_regenerate_images_requested)
        self.publish_page.publish_requested.connect(self._do_publish)
        self.publish_page.draft_requested.connect(self._do_publish_draft)
        self.publish_page.direct_image_requested.connect(self._on_direct_note_image_requested)
        self.task_list_page.draft_edit_requested.connect(self._on_draft_edit_requested)
        self.history_page.history_selected.connect(self._on_history_edit)
        self.history_page.publish_requested.connect(self._on_history_publish)
        # New pages signals
        self.hot_topics_page.generate_requested.connect(self._on_generate_from_ai_page)
        self.url_extract_page.generate_requested.connect(self._on_generate_from_ai_page)
        self.search_page.generate_requested.connect(self._on_generate_from_ai_page)

        # Load data on start
        QTimer.singleShot(500, self._load_collected_products)
        QTimer.singleShot(600, self._load_saved_notes)
        QTimer.singleShot(650, self._load_drafts_to_task_list)
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

    def _toggle_log_console(self):
        """Toggle log console visibility."""
        if self.log_console.isVisible():
            self.log_console.hide()
        else:
            self.log_console.show()

    def _notify(self, level: str, title: str, message: str, parent=None, duration: int = 6000):
        message = str(message or "")
        self._notifications.insert(0, {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "title": title,
            "message": message,
        })
        self._notifications = self._notifications[:50]
        self._notification_btn.setToolTip(f"通知中心 ({len(self._notifications)})")
        parent = parent or self
        if level == "error":
            InfoBar.error(title, message, duration=duration, parent=parent)
        elif level == "warning":
            InfoBar.warning(title, message, duration=duration, parent=parent)
        elif level == "success":
            InfoBar.success(title, message, duration=duration, parent=parent)
        else:
            InfoBar.info(title, message, duration=duration, parent=parent)

    def _open_notification_center(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("通知中心")
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(f"最近通知 ({len(self._notifications)})")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        if self._notifications:
            lines = []
            for item in self._notifications:
                lines.append(f"[{item['time']}] {item['level'].upper()} · {item['title']}\n{item['message']}")
            text.setPlainText("\n\n".join(lines))
        else:
            text.setPlainText("暂时没有通知。")
        layout.addWidget(text)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        from qfluentwidgets import PushButton

        def _clear_notifications():
            self._notifications.clear()
            self._notification_btn.setToolTip("通知中心")
            text.setPlainText("暂时没有通知。")

        clear_widget = PushButton("清空")
        clear_widget.clicked.connect(_clear_notifications)
        btn_row.addWidget(clear_widget)
        close_widget = PushButton("关闭")
        close_widget.clicked.connect(dialog.accept)
        btn_row.addWidget(close_widget)
        layout.addLayout(btn_row)
        dialog.exec_()

    def closeEvent(self, event: QCloseEvent):
        """Confirm exit if AI generation or publishing is in progress."""
        logger.info(
            "收到关闭窗口请求 | generating=%s publishing=%s visible=%s minimized=%s",
            self._is_generating,
            self._is_publishing,
            self.isVisible(),
            self.isMinimized(),
        )
        if self._is_generating or self._is_publishing:
            operations = []
            if self._is_generating:
                operations.append("AI 生成")
            if self._is_publishing:
                operations.append("发布")
            msg = QMessageBox.question(
                self,
                "确认退出",
                f"当前正在进行{'和'.join(operations)}操作，退出将中断所有进行中的任务。\n确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if msg == QMessageBox.No:
                logger.info("用户取消退出，窗口继续运行")
                event.ignore()
                return
        logger.info("窗口关闭已确认，程序准备退出")
        self._stop_background_image_loaders()
        event.accept()

    def changeEvent(self, event):
        """Keep minimized windows visible in the taskbar."""
        super().changeEvent(event)

    def _setup_tray_icon(self):
        """Set up system tray icon with context menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray not available")
            return

        self._tray_icon = QSystemTrayIcon(self)
        # Try to use application icon, fall back to default
        app_icon = QApplication.instance().windowIcon()
        if app_icon.isNull():
            from qfluentwidgets import FluentIcon as _FI
            try:
                self._tray_icon.setIcon(_FI.CONSOLE.icon())
            except Exception:
                pass
        else:
            self._tray_icon.setIcon(app_icon)
        self._tray_icon.setToolTip("小红书自动发布系统")

        # Context menu
        tray_menu = QMenu(self)
        restore_action = QAction("显示主窗口", self)
        restore_action.triggered.connect(self._restore_from_tray)
        tray_menu.addAction(restore_action)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        self._tray_icon.setContextMenu(tray_menu)

        # Double-click to restore
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _on_tray_activated(self, reason):
        """Handle tray icon activation events."""
        if reason == QSystemTrayIcon.DoubleClick:
            self._restore_from_tray()

    def _restore_from_tray(self):
        """Restore window from system tray."""
        self.show()
        self.showNormal()
        self.activateWindow()

    def _show_tray_notification(self, title: str, message: str):
        """Show a system tray balloon notification."""
        if self._tray_icon and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 5000)

    def _stop_background_image_loaders(self):
        """Stop page image loaders before widgets are destroyed."""
        for page in (
            self.task_list_page,
            self.ai_generate_page,
            self.publish_page,
        ):
            loader = getattr(page, "_image_loader", None)
            if loader and hasattr(loader, "stop"):
                try:
                    loader.stop()
                except Exception as e:
                    logger.debug("停止图片加载器失败: %s", e)

    def _process_next_in_queue(self):
        """Process the next product in the batch generation queue."""
        if not self._generate_queue:
            self._is_generating = False
            if self._generate_total:
                self.task_list_page.set_batch_progress(self._generate_total, self._generate_total, done=True)
            return

        product = self._generate_queue.pop(0)
        current_index = self._generate_total - len(self._generate_queue)
        self.task_list_page.set_batch_progress(current_index, self._generate_total, product.get("title", ""))
        self.ai_generate_page.set_product(product)
        self.ai_generate_page.set_generating(True)
        self._images_shown_early = False
        style = self.ai_generate_page.style_combo.currentText()
        self.ai_backend.generate(product, style)

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
                logger.warning("API key check failed: %s", e)

            try:
                from src.ai.image_generator import check_kimi_health, kimi_health_message
                if not check_kimi_health():
                    warnings.append(kimi_health_message(start_if_needed=True))
            except Exception as e:
                logger.warning("Kimi health check failed: %s", e)
                warnings.append("Kimi WebBridge 检查失败（无法确认生图能力）")

            self.api_check_done.emit(warnings)

        threading.Thread(target=_run, daemon=True).start()

    def _show_api_check_warnings(self, warnings: list):
        if warnings:
            self._notify(
                "warning",
                "系统检查",
                summarize_errors(warnings),
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
                    "item_id": p.get("item_id", ""),
                    "title": p.get("title", ""),
                    "local_images": p.get("local_images", [])[:image_limit],
                    "main_images": p.get("main_images", [])[:image_limit],
                    "detail_images": p.get("detail_images", [])[:image_limit],
                    "status": "pending",
                })
            self.task_list_page.load_products(products)
            logger.info("Loaded %s products", len(products))
            # 同步刷新 AI 生成页的商品下拉框
            try:
                self.ai_generate_page.load_products()
            except Exception as e2:
                logger.warning("Failed to load products into AI page: %s", e2)
        except Exception as e:
            logger.error("Failed to load products: %s", e)

    def _load_saved_notes(self):
        """Load saved generated notes into publish page"""
        try:
            from src.database.generated_store import get_all_notes
            notes = get_all_notes()
            items = [self.publish_page._build_item_from_note(n) for n in notes]
            self.publish_page.load_items(items)
            logger.info("Loaded %s saved notes", len(notes))
        except Exception as e:
            logger.error("Failed to load saved notes: %s", e)

    def _load_drafts_to_task_list(self):
        """Load draft notes into the task list page draft area"""
        try:
            from src.database.generated_store import get_all_notes
            notes = get_all_notes()
            self.task_list_page.load_drafts(notes)
        except Exception as e:
            logger.error("Failed to load drafts to task list: %s", e)

    def _on_draft_edit_requested(self, note_id: int):
        """Handle edit request from task list draft card — load note into AI page."""
        try:
            from src.database.generated_store import get_all_notes
            notes = get_all_notes()
            note = None
            for n in notes:
                if n.get("id") == note_id:
                    note = n
                    break
            if not note:
                logger.warning("Draft note id=%s not found", note_id)
                return
            # Switch to AI generate page
            self.switchTo(self.ai_generate_page)
            # Load the note content into the editor
            self.ai_generate_page.set_content(
                note.get("title", ""),
                note.get("content", ""),
                note.get("tags", ""),
            )
            # Set up saved note ids so save updates this note
            # Find all notes with same product to rebuild the note_ids list
            product_name = note.get("product_name", "")
            same_product_notes = [n for n in notes if n.get("product_name") == product_name]
            note_ids = [n.get("id") for n in same_product_notes]
            self.ai_generate_page.set_saved_note_ids(note_ids)
            # Try to find the variant index
            variant_idx = note.get("selected_variant_index", 0)
            if note.get("variants"):
                self.ai_generate_page.set_posts(note["variants"], [])
                self.ai_generate_page._show_post(min(variant_idx, len(note["variants"]) - 1))
            logger.info("Loaded draft note id=%s for editing", note_id)
        except Exception as e:
            logger.error("Failed to load draft for editing: %s", e)

    def _find_collected_product_for_note(self, item: dict) -> dict | None:
        """Find a collected product that can provide the real product image."""
        if not os.path.exists(PRODUCTS_JSON):
            return None
        try:
            with open(PRODUCTS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("Load collected products for note image failed: %s", e)
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
        """Handle generate request from task list — batch queue processing."""
        if not products:
            return
        self._generate_queue = list(products)
        self._generate_total = len(self._generate_queue)
        self._is_generating = True

        # Process first product immediately
        product = self._generate_queue.pop(0)
        self.ai_generate_page.set_product(product)
        self.task_list_page.set_batch_progress(1, self._generate_total, product.get("title", ""))

        self.ai_generate_page.set_generating(True)
        self._images_shown_early = False
        style = self.ai_generate_page.style_combo.currentText()
        self.ai_backend.generate(product, style)

    def _on_generate_from_ai_page(self, data):
        product = data.get("product") if isinstance(data, dict) else None
        if not product:
            InfoBar.warning("提示", "请先从任务列表选择产品", parent=self.ai_generate_page)
            return

        # 切换到 AI 生成页面（从热点/URL/搜索页面触发时需要跳转）
        try:
            self.switchTo(self.ai_generate_page)
        except Exception:
            pass  # 如果已经在 AI 页面，switchTo 可能报错，忽略

        # 获取选中的文案模板文本
        content_template_key = data.get("content_template_key", "")
        content_template_text = ""
        if content_template_key:
            try:
                from src.config import get_config_manager
                cfg = get_config_manager()
                prompts = cfg.get("prompts", {})
                if isinstance(prompts, dict):
                    content_template_text = prompts.get(content_template_key, "")
                # 如果 config 里没有，从 prompt_templates.py 的默认值读取
                if not content_template_text:
                    from src.ai.prompt_templates import _get_template_by_key
                    content_template_text = _get_template_by_key(content_template_key)
            except Exception as e:
                logger.warning("Load content template failed: %s", e)

        # 弹出提示词预览对话框，确认后再开始生成
        from .widgets.prompt_preview_dialog import PromptPreviewDialog
        preview = PromptPreviewDialog(
            product=product,
            style=data.get("style", "种草推荐"),
            parent=self,
        )
        preview.settings_requested.connect(self._on_jump_to_settings)
        if preview.exec_() != PromptPreviewDialog.Accepted:
            return  # 用户取消或去设置

        self.ai_generate_page.set_product(product)
        self.ai_generate_page.set_generating(True)
        self._images_shown_early = False
        # 传递选中的模型信息和文案模板
        self.ai_backend.generate(
            product,
            data.get("style", "种草推荐"),
            provider=data.get("model_provider"),
            model=data.get("model_name"),
            content_template=content_template_text,
            search_results=data.get("search_results", ""),  # 搜索结果
        )

    def _on_jump_to_settings(self):
        """从提示词预览对话框跳转到设置页"""
        self.switchTo(self.settings_page)

    def _on_images_ready(self, data):
        """Images finished — display them in AI page immediately, without waiting for content."""
        image_results = data.get("image_results", [])
        if image_results:
            self.ai_generate_page.set_image_results(image_results)
        else:
            images = data.get("images", [])
            if images:
                self.ai_generate_page.set_images(images)
        self._images_shown_early = True

    def _on_directions_ready(self, data: dict):
        """第一轮（方向生成）完成，提前刷新方向下拉框"""
        directions = data.get("directions", [])
        logger.info("✓ 收到 direction_done 信号，方向数: %d", len(directions))
        if directions:
            logger.info("  方向列表: %s", [d.get('name', d) for d in directions[:3]])
        else:
            logger.warning("  ⚠ 方向列表为空！")

        # 先只传方向，posts 等第二轮完成后再刷新
        self.ai_generate_page.set_posts([], directions)

        # 确保切换到 AI 生成页面
        try:
            self.switchTo(self.ai_generate_page)
        except Exception:
            pass

    def _on_ai_done(self, result):
        """AI generation finished - save to store"""
        try:
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
            # Skip image display if already shown via images_ready signal
            if not self._images_shown_early:
                if image_results:
                    self.ai_generate_page.set_image_results(image_results)
                else:
                    self.ai_generate_page.set_images(images)
            self._images_shown_early = False
            self.ai_generate_page.set_posts(posts, directions)

            # Show warnings/errors to user
            from src.utils.error_messages import is_cloudflare_error
            has_cloudflare = any(is_cloudflare_error(w) for w in warnings)
            if errors and not posts:
                # 严重错误：所有生成都失败了，弹模态对话框确保用户看到
                msg = summarize_errors(errors)
                from PyQt5.QtWidgets import QMessageBox
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Warning)
                box.setWindowTitle("生成失败")
                box.setText("本次生成全部失败，请检查配置后重试。")
                box.setDetailedText(msg)
                box.setStandardButtons(QMessageBox.Ok)
                box.show()
                self._notify("error", "生成失败", msg, parent=self.ai_generate_page, duration=8000)
            elif errors:
                msg = summarize_errors(errors)
                self._notify("error", "生成出错", msg, duration=8000, parent=self.ai_generate_page)
            elif has_cloudflare:
                self._notify(
                    "warning",
                    "ChatGPT 被拦截",
                    "图片生成遇到 Cloudflare 拦截，请检查代理设置。可稍后重试缺失图片。",
                    duration=8000, parent=self.ai_generate_page,
                )
            elif warnings:
                msg = summarize_errors(warnings)
                self._notify("warning", "部分完成", msg, duration=6000, parent=self.ai_generate_page)
            elif posts:
                self._notify(
                    "success",
                    "生成完成",
                    f"{len(directions)} 个方向 × 3 篇 = {len(posts)} 篇文案 + {len(images)} 张图片",
                    parent=self.ai_generate_page,
                )
            else:
                self._notify("success", "生成完成", "标题+文案已生成（无图片）", parent=self.ai_generate_page)

            # Save 9 independent draft notes (one per variant)
            try:
                from src.database.generated_store import save_note
                note_ids = []
                if posts:
                    for idx, post in enumerate(posts):
                        note = save_note(
                            title=post.get("title", ""),
                            content=post.get("content", ""),
                            tags=post.get("tags", ""),
                            images=images,  # 共享图片
                            product_name=product_name,
                            status="draft",
                            direction_id=post.get("direction_id", ""),
                            direction_name=post.get("direction_name", ""),
                            variants=posts,              # 保留全量变体供 AI 页切换
                            selected_variant_index=idx,
                        )
                        note_ids.append(note.get("id"))
                    self.ai_generate_page.set_saved_note_ids(note_ids)
                    logger.info("Saved %d draft notes for %s", len(note_ids), product_name)
            except Exception as e:
                logger.error("Save notes failed: %s", e)

            # Reload publish page and task list drafts
            self._load_saved_notes()
            self._load_drafts_to_task_list()

            # Tray notification
            self._show_tray_notification("生成完成", f"{product_name} 内容已生成")
        finally:
            self.ai_generate_page.set_generating(False)
            self._process_next_in_queue()

    def _on_retry_images_requested(self, indices):
        product = self.ai_generate_page.get_product()
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
            logger.error("Update note images failed: %s", e)

        self._load_saved_notes()
        if warnings:
            InfoBar.warning("图片未补齐", summarize_errors(warnings), duration=6000, parent=self.ai_generate_page)
        elif self.ai_generate_page.get_missing_image_indices():
            InfoBar.warning("图片未补齐", "仍有图片生成失败，可继续重试", duration=5000, parent=self.ai_generate_page)
        else:
            InfoBar.success("图片已补齐", "3 张图片都已生成", parent=self.ai_generate_page)

    def _on_regenerate_content_requested(self, data: dict):
        """UI 请求重新生成某个方向的文案"""
        product = data.get("product")
        direction_data = data.get("direction_data", {})
        style = data.get("style", "种草")
        provider = data.get("model_provider")
        model = data.get("model_name")
        template_key = data.get("content_template_key", "")
        # 读取模板内容
        content_template = ""
        if template_key:
            import json
            from src.ai.prompt_templates import _get_template_by_key
            try:
                config_path = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "config.json")
                if os.path.exists(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    overrides = config.get("prompt_overrides", {})
                    content_template = overrides.get(template_key, "")
                if not content_template:
                    content_template = _get_template_by_key(template_key)
            except Exception:
                from src.ai.prompt_templates import _get_template_by_key
                content_template = _get_template_by_key(template_key)
        self.ai_generate_page.set_generating(True)
        self.ai_backend.regenerate_content(
            product=product,
            direction_data=direction_data,
            style=style,
            provider=provider,
            model=model,
            content_template=content_template,
        )

    def _on_regenerate_images_requested(self, data: dict):
        """UI 请求重新生成图片"""
        product = data.get("product")
        existing_images = data.get("existing_images", [])
        self.ai_generate_page.set_generating(True)
        self.ai_backend.regenerate_images(product, existing_images)

    def _on_content_regenerated(self, result: dict):
        """后端文案重生成完成，更新 UI"""
        direction_id = result.get("direction_id", "")
        new_posts = result.get("posts", [])
        error = result.get("error", "")

        if error:
            InfoBar.error("文案重生成失败", error, parent=self.ai_generate_page)
            self.ai_generate_page.set_generating(False)
            return

        # 更新 ai_generate_page 的 _posts 里对应方向的 3 篇
        if not hasattr(self.ai_generate_page, "_posts"):
            self.ai_generate_page.set_generating(False)
            return
        old_posts = self.ai_generate_page._posts
        # 去掉旧的方向文案，加入新的
        kept = [p for p in old_posts if p.get("direction_id") != direction_id]
        kept.extend(new_posts)
        # 按方向顺序重排
        directions = self.ai_generate_page._directions
        dir_order = {d["id"]: i for i, d in enumerate(directions)}
        kept.sort(key=lambda p: (dir_order.get(p["direction_id"], 99), p.get("hook_style", "")))
        self.ai_generate_page._posts = kept

        # 刷新帖子索引面板
        self.ai_generate_page._build_post_index_panel()
        # 显示该方向的第一篇
        for i, p in enumerate(kept):
            if p.get("direction_id") == direction_id:
                self.ai_generate_page._show_post(i)
                break

        self.ai_generate_page.set_generating(False)
        InfoBar.success(
            "文案已更新",
            f"方向「{result.get('direction_name', '')}」3 篇文案已重新生成",
            parent=self.ai_generate_page,
        )

    def _on_images_regenerated(self, result: dict):
        """后端图片重生成完成，更新 UI"""
        images = result.get("images", [])
        image_results = result.get("image_results", [])
        warnings = result.get("warnings", [])

        if image_results:
            self.ai_generate_page.set_image_results(image_results)
        else:
            self.ai_generate_page.set_images(images)

        self.ai_generate_page.set_generating(False)

        if warnings:
            InfoBar.warning("图片重生成", summarize_errors(warnings), parent=self.ai_generate_page)
        else:
            InfoBar.success("图片已更新", f"已重新生成 {len(images)} 张图片", parent=self.ai_generate_page)
    def _on_direct_note_image_requested(self, item: dict):
        note_id = item.get("id")
        if not note_id:
            InfoBar.warning("无法生成", "这条记录没有笔记 ID", parent=self.publish_page)
            return

        product = self._find_collected_product_for_note(item)
        if product:
            logger.info("Found product image for note id=%s: %s", note_id, product.get('title', '')[:30])
        else:
            logger.info("No collected product matched for note id=%s, using prompt-only image generation", note_id)

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
                logger.error("Update note direct images failed: %s", e)
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
                InfoBar.warning("生成提示", summarize_errors(warnings), duration=6000, parent=self.publish_page)
        else:
            message = summarize_errors(warnings) if warnings else "没有生成可用图片"
            InfoBar.warning("直接生成失败", message, duration=8000, parent=self.publish_page)

    # ============================================================
    # 发布
    # ============================================================

    def _on_save_current_draft(self, data):
        """Save/update the draft note for the currently selected variant."""
        title = data.get("title", "")
        content = data.get("content", "")
        tags = data.get("tags", "")
        images = data.get("images", [])
        product_name = data.get("product_name", "")
        variant_index = data.get("selected_variant_index", 0)

        if not title or not content:
            InfoBar.warning("提示", "请先生成内容再保存", parent=self.ai_generate_page)
            return

        try:
            from src.database.generated_store import save_note, update_note
            # Pick the correct note_id for the current variant
            saved_ids = self.ai_generate_page.get_saved_note_ids()
            note_id = saved_ids[variant_index] if variant_index < len(saved_ids) else None

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
                    selected_variant_index=variant_index,
                )
                logger.info("Updated draft note id=%s (variant %d)", note_id, variant_index)
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
                    selected_variant_index=variant_index,
                )
                new_id = note.get("id")
                # Append the new id at the right position
                while len(saved_ids) <= variant_index:
                    saved_ids.append(None)
                saved_ids[variant_index] = new_id
                self.ai_generate_page.set_saved_note_ids(saved_ids)
                logger.info("Saved new draft note id=%s (variant %d)", new_id, variant_index)
            self._load_saved_notes()
            self._load_drafts_to_task_list()
        except Exception as e:
            logger.error("Save current draft failed: %s", e)
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
                logger.info("Updated current note id=%s to pending", note_id)
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
                    logger.info("Updated existing note id=%s to pending", matched['id'])
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
            logger.error("Save failed: %s", e)

        # Reload publish page
        self._load_saved_notes()
        InfoBar.success("加入队列", f"「{title[:20]}」已加入发布队列", parent=self)
        self.switchTo(self.publish_page)

    def _on_prompt_edit_requested(self):
        """AI 生成页点「提示词」按钮，跳转到设置页的提示词区域"""
        self.switchTo(self.settings_page)
        # 让设置页滚动到提示词卡片（通过调用 settings_page 的方法）
        if hasattr(self.settings_page, 'scroll_to_prompts'):
            self.settings_page.scroll_to_prompts()

    def _on_history_edit(self, data: dict):
        """从历史页选中某条记录，加载到 AI 生成页进行编辑"""
        try:
            title = data.get("title", "")
            content = data.get("content", "")
            tags = data.get("tags", "")
            product_name = data.get("product_name", "")

            # 构造一个 fake product 填入 AI 生成页
            from src.database.generated_store import get_all_notes
            notes = get_all_notes()
            note_id = data.get("id")

            self.switchTo(self.ai_generate_page)
            self.ai_generate_page.set_content(title, content, tags)

            InfoBar.info("编辑历史", f"已加载「{title[:20]}」", parent=self)
        except Exception as e:
            logger.error("History edit failed: %s", e)
            InfoBar.error("错误", f"加载历史记录失败: {e}", parent=self)

    def _on_history_publish(self, data: dict):
        """从历史页请求发布某条记录"""
        try:
            items = [data]
            self._do_publish(items, draft=False)
        except Exception as e:
            logger.error("History publish failed: %s", e)
            InfoBar.error("错误", f"发布失败: {e}", parent=self)

    def _do_publish(self, items, draft=False):
        """Publish via CLI subprocess. draft=True saves to drafts box instead of public publish."""
        if not items:
            InfoBar.warning("提示", "没有要发布的笔记", parent=self)
            return
        if self._is_publishing:
            InfoBar.warning("提示", "正在发布中，请等待完成", parent=self)
            return

        mode_text = "发布到草稿箱" if draft else "发布"
        self._is_publishing = True
        InfoBar.info(f"开始{mode_text}", f"正在{mode_text} {len(items)} 个笔记...", parent=self)

        def _publish_thread():
            success_count = 0
            error_count = 0
            try:
                import subprocess
                from src.database.generated_store import update_note_status

                for i, item in enumerate(items):
                    title = item.get("title", "")
                    content = item.get("content", "")
                    tags = item.get("tags", "")
                    images = item.get("images", [])
                    note_id = item.get("id")

                    logger.info("%s %s/%s: %s", mode_text, i+1, len(items), title[:30])
                    self.publish_progress.emit(i + 1, len(items))

                    # Write temp files
                    tmp_dir = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "_publish_tmp")
                    os.makedirs(tmp_dir, exist_ok=True)

                    title_file = os.path.join(tmp_dir, "title.txt")
                    content_file = os.path.join(tmp_dir, "content.txt")
                    with open(title_file, "w", encoding="utf-8") as f:
                        f.write(title)
                    with open(content_file, "w", encoding="utf-8") as f:
                        f.write(content)
                        if tags:
                            f.write("\n\n" + tags)

                    # Build command through the package CLI so installed and
                    # source checkouts behave the same.
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    cmd = [
                        sys.executable,
                        "-m",
                        "src.publisher.cli_publisher",
                        "--title-file",
                        title_file,
                        "--content-file",
                        content_file,
                        "--auto",
                        "--json",
                    ]
                    if draft:
                        cmd.append("--draft")
                    valid_images = [img for img in images if os.path.exists(img)]
                    if valid_images:
                        cmd.append("--images")
                        cmd.extend(valid_images)
                    if tags:
                        cmd.extend(["--tags", tags])

                    # Run CLI (设置 cwd 为项目根目录，确保能找到 src 模块)
                    env = os.environ.copy()
                    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=300,
                        encoding="utf-8", errors="replace",
                        cwd=project_root,
                        env=env,
                    )

                    # Parse JSON output（取最后一个完整 JSON）
                    parsed = None
                    stdout = result.stdout.strip()
                    last_brace = stdout.rfind("{")
                    if last_brace >= 0:
                        for end in range(len(stdout), last_brace, -1):
                            try:
                                parsed = json.loads(stdout[last_brace:end])
                                break
                            except json.JSONDecodeError:
                                continue
                    if not parsed:
                        for line in reversed(stdout.splitlines()):
                            line = line.strip()
                            if line.startswith("{"):
                                try:
                                    parsed = json.loads(line)
                                    break
                                except json.JSONDecodeError:
                                    continue

                    if parsed and parsed.get("success"):
                        success_count += 1
                        logger.info("%s成功: %s", mode_text, title[:30])
                        if draft:
                            item["status"] = "已存草稿"
                            if note_id:
                                update_note_status(note_id, "draft_saved")
                        else:
                            item["status"] = "已发布"
                            if note_id:
                                update_note_status(note_id, "published")
                    else:
                        error_count += 1
                        error = (parsed or {}).get("message") or result.stderr[-200:] or "未知错误"
                        friendly_error = explain_error(error)
                        logger.error("%s失败: %s", mode_text, friendly_error)
                        item["status"] = "失败"
                        if note_id:
                            update_note_status(note_id, "failed", error=friendly_error)

                self.publish_summary.emit(mode_text, success_count, error_count)

            except subprocess.TimeoutExpired:
                logger.error("%s超时", mode_text)
                self.publish_error.emit("发布超时", f"{mode_text}操作超过时限已中止，请检查网络后重试")
            except Exception as e:
                logger.error("%s异常: %s", mode_text, e)
                self.publish_error.emit("发布异常", str(e)[:120])

        threading.Thread(target=_publish_thread, daemon=True).start()

    def _do_publish_draft(self, items):
        """Publish items to XHS drafts box (草稿箱)"""
        self._do_publish(items, draft=True)

    def _show_publish_summary(self, mode_text: str, success_count: int, error_count: int):
        """Show publish result on the GUI thread."""
        self._load_saved_notes()
        self._is_publishing = False
        if error_count == 0:
            self._notify(
                "success",
                "发布完成",
                f"全部 {success_count} 个笔记{mode_text}成功",
                duration=6000,
                parent=self,
            )
        else:
            self._notify(
                "warning",
                f"{mode_text}完成",
                f"成功 {success_count} 个，失败 {error_count} 个",
                duration=8000,
                parent=self,
            )
        self._show_tray_notification(
            f"{mode_text}完成",
            f"成功 {success_count}，失败 {error_count}",
        )

    def _show_publish_error(self, title: str, message: str):
        """Show publish errors on the GUI thread."""
        self._is_publishing = False
        self._notify("error", title, message, duration=8000, parent=self.publish_page)


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
