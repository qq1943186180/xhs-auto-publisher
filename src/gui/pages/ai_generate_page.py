"""
AI Generate Page - 两轮生成：方向 → 文案（3方向 × 3篇 = 9篇）
"""
import logging
import os
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget, QLabel, QSizePolicy,
    QScrollArea, QFrame, QSplitter,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, PlainTextEdit,
    LineEdit, ComboBox, ProgressBar, InfoBar, StrongBodyLabel,
    BodyLabel, CaptionLabel, ToolButton, FluentIcon,
)
from src.gui.styles.theme import (
    BORDER,
    ERROR,
    INFO,
    PRIMARY,
    SURFACE_ALT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    page_subtitle_style,
    page_title_style,
    placeholder_style,
)
from src.gui.utils import PAGE_MARGINS
from src.gui.workers.image_loader import AsyncImageLoader, _create_placeholder_pixmap


class AIGeneratePage(QWidget):
    """AI content generation page - 两轮生成"""

    generate_clicked = pyqtSignal(dict)
    save_clicked = pyqtSignal(dict)
    publish_clicked = pyqtSignal(dict)
    retry_images_clicked = pyqtSignal(list)
    prompt_edit_requested = pyqtSignal()  # 请求跳转到提示词编辑
    regenerate_content_clicked = pyqtSignal(dict)  # 重新生成当前篇文案
    regenerate_images_clicked = pyqtSignal(dict)   # 重新生成当前商品图片

    IMAGE_STYLE_LABELS = ["博主风", "纯白简约", "氛围场景"]
    STEP_ORDER = [
        ("direction_generating", "方向"),
        ("image_generating", "图片"),
        ("content_generating", "文案"),
        ("completed", "完成"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._product = None
        self._is_generating = False
        self._is_retrying_images = False
        self._has_image_attempt = False
        self._generated_images = []
        self._image_slots = []
        self._saved_note_ids = []
        self._posts = []           # 全部 9 篇
        self._directions = []      # 3 个方向
        self._current_post_idx = 0
        self._model_entries = []
        self._image_loader = AsyncImageLoader(self)
        self._image_loader.image_loaded.connect(self._on_image_loaded)
        self._search_results = []  # 搜索结果
        self._search_results_text = ""  # 格式化的搜索结果文本
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGINS)
        layout.setSpacing(16)

        # ===== Header: 商品选择 + 标题 + 方向/帖子导航 =====
        header = QHBoxLayout()

        # 商品下拉选择（放在最左边，优先显示）
        header.addWidget(CaptionLabel("商品:"))
        self.product_combo = ComboBox()
        self.product_combo.setFixedWidth(220)
        self.product_combo.setToolTip("选择要生成内容的商品")
        self.product_combo.currentIndexChanged.connect(self._on_product_combo_changed)
        header.addWidget(self.product_combo)

        header.addSpacing(16)

        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel("AI 内容生成")
        title.setStyleSheet(page_title_style())
        title_box.addWidget(title)
        subtitle = QLabel("选商品 → 调提示词 → 生成文案+图片，9 版用于挑选")
        subtitle.setStyleSheet(page_subtitle_style())
        title_box.addWidget(subtitle)
        header.addLayout(title_box)

        # 方向选择器
        header.addSpacing(24)
        header.addWidget(CaptionLabel("方向:"))
        self.direction_combo = ComboBox()
        self.direction_combo.setFixedWidth(180)
        self.direction_combo.currentIndexChanged.connect(self._on_direction_changed)
        header.addWidget(self.direction_combo)

        # 帖子导航
        header.addSpacing(16)
        self.post_nav_label = CaptionLabel("")
        header.addWidget(self.post_nav_label)

        self.prev_btn = ToolButton(FluentIcon.LEFT_ARROW)
        self.prev_btn.setFixedSize(36, 32)
        self.prev_btn.setToolTip("上一篇")
        self.prev_btn.clicked.connect(self._prev_post)
        header.addWidget(self.prev_btn)

        self.next_btn = ToolButton(FluentIcon.RIGHT_ARROW)
        self.next_btn.setFixedSize(36, 32)
        self.next_btn.setToolTip("下一篇")
        self.next_btn.clicked.connect(self._next_post)
        header.addWidget(self.next_btn)

        header.addSpacing(16)

        # 文案模板选择器
        header.addWidget(CaptionLabel("文案模板:"))
        self.template_combo = ComboBox()
        self.template_combo.setFixedWidth(160)
        self.template_combo.addItem("默认系统提示词", userData="")
        self.template_combo.addItem("日常种草", userData="content_template_1")
        self.template_combo.addItem("真实测评", userData="content_template_2")
        self.template_combo.addItem("搭配灵感", userData="content_template_3")
        self.template_combo.addItem("选购参考", userData="content_template_4")
        self.template_combo.addItem("日常记录", userData="content_template_5")
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        header.addWidget(self.template_combo)

        # 编辑模板按钮
        self.edit_template_btn = PushButton("编辑模板")
        self.edit_template_btn.setFixedHeight(32)
        self.edit_template_btn.setMinimumWidth(90)
        self.edit_template_btn.setToolTip("编辑当前选中的文案模板")
        self.edit_template_btn.clicked.connect(self._on_edit_template)
        header.addWidget(self.edit_template_btn)

        header.addStretch()

        # 搜索资料按钮
        self.search_btn = PushButton("搜索资料")
        self.search_btn.setFixedHeight(32)
        self.search_btn.setMinimumWidth(100)
        self.search_btn.setToolTip("搜索相关资料，用于丰富生成内容")
        self.search_btn.clicked.connect(self._on_open_search)
        header.addWidget(self.search_btn)

        # 提示词按钮：跳去设置页编辑提示词
        self.prompt_edit_btn = PrimaryPushButton("提示词")
        self.prompt_edit_btn.setFixedHeight(32)
        self.prompt_edit_btn.setMinimumWidth(100)
        self.prompt_edit_btn.setToolTip("编辑文案/图片生成提示词")
        self.prompt_edit_btn.clicked.connect(self._on_prompt_edit)
        header.addWidget(self.prompt_edit_btn)

        # 帖子总数标签
        self.total_label = CaptionLabel("")
        self.total_label.setStyleSheet(f"color: {TEXT_MUTED};")
        header.addWidget(self.total_label)

        layout.addLayout(header)

        # ===== Progress bar =====
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.step_row = QHBoxLayout()
        self.step_row.setSpacing(8)
        self._step_labels = []
        for _, label_text in self.STEP_ORDER:
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumWidth(72)
            self._step_labels.append(label)
            self.step_row.addWidget(label)
        self.step_row.addStretch()
        layout.addLayout(self.step_row)
        self._set_active_step(None)

        # ===== Status label (生成中显示) =====
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        # ===== Main content area =====
        splitter = QSplitter(Qt.Horizontal)

        # ===== Left: 3 image previews + post index panel =====
        left_card = CardWidget(self)
        left_card.setMinimumWidth(300)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        self.product_name_label = StrongBodyLabel("未选择产品")
        left_layout.addWidget(self.product_name_label)

        img_row = QHBoxLayout()
        img_row.setSpacing(8)
        self.img_previews = []
        for i in range(3):
            img_col = QVBoxLayout()
            img_col.setSpacing(4)
            img_label = QLabel("等待生成...")
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setMinimumSize(200, 260)
            img_label.setMaximumHeight(280)
            img_label.setCursor(Qt.PointingHandCursor)
            img_label.mousePressEvent = lambda event, idx=i: self._on_image_clicked(idx)
            img_label.setStyleSheet(placeholder_style())
            img_col.addWidget(img_label)
            tag = CaptionLabel(self.IMAGE_STYLE_LABELS[i])
            tag.setAlignment(Qt.AlignCenter)
            img_col.addWidget(tag)
            img_row.addLayout(img_col)
            self.img_previews.append(img_label)

        left_layout.addLayout(img_row)

        retry_row = QHBoxLayout()
        retry_row.addStretch()
        self.retry_images_btn = PushButton("重试缺失图片")
        self.retry_images_btn.setFixedHeight(34)
        self.retry_images_btn.clicked.connect(self._on_retry_missing_images)
        self.retry_images_btn.hide()
        retry_row.addWidget(self.retry_images_btn)
        left_layout.addLayout(retry_row)

        # 方向信息卡片
        left_layout.addSpacing(8)
        self.direction_info_card = CardWidget(self)
        di_layout = QVBoxLayout(self.direction_info_card)
        di_layout.setContentsMargins(12, 10, 12, 10)
        di_layout.setSpacing(4)
        self.dir_name_label = StrongBodyLabel("")
        self.dir_audience_label = BodyLabel("")
        self.dir_angle_label = BodyLabel("")
        self.dir_hook_label = BodyLabel("")
        di_layout.addWidget(self.dir_name_label)
        di_layout.addWidget(self.dir_audience_label)
        di_layout.addWidget(self.dir_angle_label)
        di_layout.addWidget(self.dir_hook_label)
        self.direction_info_card.hide()
        left_layout.addWidget(self.direction_info_card)

        # 帖子索引面板（3×3 网格小卡片）
        left_layout.addSpacing(8)
        self.post_index_panel = QScrollArea()
        self.post_index_panel.setWidgetResizable(True)
        self.post_index_panel.setMaximumHeight(220)
        self.post_index_panel.setFrameShape(QScrollArea.NoFrame)
        self._post_index_container = QWidget()
        self._post_index_grid = QGridLayout(self._post_index_container)
        self._post_index_grid.setContentsMargins(0, 0, 0, 0)
        self._post_index_grid.setSpacing(6)
        self.post_index_panel.setWidget(self._post_index_container)
        left_layout.addWidget(self.post_index_panel)

        left_layout.addStretch()
        splitter.addWidget(left_card)

        # ===== Right: editor =====
        right_card = CardWidget(self)
        right_card.setMinimumWidth(400)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        # 风格选择器（生成前用）
        style_row = QHBoxLayout()
        style_row.addWidget(BodyLabel("风格:"))
        self.style_combo = ComboBox()
        self.style_combo.addItems(["种草推荐", "产品测评", "使用教程"])
        self.style_combo.setFixedWidth(150)
        style_row.addWidget(self.style_combo)

        # 模型选择器
        style_row.addWidget(BodyLabel("模型:"))
        self.model_combo = ComboBox()
        self.model_combo.setFixedWidth(220)
        self._refresh_model_list()
        style_row.addWidget(self.model_combo)

        refresh_model_btn = PushButton("刷新")
        refresh_model_btn.setFixedWidth(50)
        refresh_model_btn.clicked.connect(self._refresh_model_list)
        style_row.addWidget(refresh_model_btn)

        style_row.addStretch()

        # 帖子序号标签
        self.post_index_label = StrongBodyLabel("")
        self.post_index_label.setStyleSheet(f"color: {PRIMARY};")
        style_row.addWidget(self.post_index_label)
        right_layout.addLayout(style_row)

        # 标题
        right_layout.addWidget(BodyLabel("标题:"))
        self.title_edit = LineEdit()
        self.title_edit.setPlaceholderText("AI生成的标题...")
        self.title_edit.setFixedHeight(40)
        self.title_edit.textChanged.connect(self._refresh_metrics)
        right_layout.addWidget(self.title_edit)

        # 正文
        right_layout.addWidget(BodyLabel("正文:"))
        self.content_edit = PlainTextEdit()
        self.content_edit.setPlaceholderText("AI生成的文案...")
        self.content_edit.textChanged.connect(self._refresh_metrics)
        right_layout.addWidget(self.content_edit)

        # 话题标签
        right_layout.addWidget(BodyLabel("话题标签:"))
        self.tags_edit = LineEdit()
        self.tags_edit.setPlaceholderText("#话题1 #话题2 #话题3")
        self.tags_edit.setFixedHeight(40)
        self.tags_edit.textChanged.connect(self._refresh_metrics)
        right_layout.addWidget(self.tags_edit)

        metrics_row = QHBoxLayout()
        self.metrics_label = CaptionLabel("标题 0/20 · 正文 0/1000 · 标签 0")
        self.metrics_label.setStyleSheet(f"color: {TEXT_MUTED};")
        metrics_row.addWidget(self.metrics_label)
        metrics_row.addStretch()
        right_layout.addLayout(metrics_row)

        preview_card = CardWidget(self)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 12, 14, 12)
        preview_layout.setSpacing(8)
        preview_title = QLabel("小红书预览")
        preview_title.setStyleSheet(f"font-weight: 700; color: {TEXT_PRIMARY};")
        preview_layout.addWidget(preview_title)
        self.preview_title_label = QLabel("标题预览")
        self.preview_title_label.setWordWrap(True)
        self.preview_title_label.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {TEXT_PRIMARY};")
        preview_layout.addWidget(self.preview_title_label)
        self.preview_content_label = QLabel("正文预览")
        self.preview_content_label.setWordWrap(True)
        self.preview_content_label.setMaximumHeight(120)
        self.preview_content_label.setStyleSheet(f"color: {TEXT_SECONDARY}; line-height: 1.4;")
        preview_layout.addWidget(self.preview_content_label)
        self.preview_tags_label = QLabel("")
        self.preview_tags_label.setWordWrap(True)
        self.preview_tags_label.setStyleSheet(f"color: {PRIMARY};")
        preview_layout.addWidget(self.preview_tags_label)
        right_layout.addWidget(preview_card)

        # ===== Buttons =====
        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(12)
        action_grid.setVerticalSpacing(12)

        self.generate_btn = PrimaryPushButton("生成内容与图片")
        self.generate_btn.setFixedHeight(44)
        self.generate_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.generate_btn.clicked.connect(self._on_generate)
        action_grid.addWidget(self.generate_btn, 0, 0)

        self.save_btn = PushButton("保存当前篇")
        self.save_btn.setFixedHeight(44)
        self.save_btn.setMinimumWidth(140)
        self.save_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self._on_save)
        action_grid.addWidget(self.save_btn, 0, 1)

        self.publish_btn = PrimaryPushButton("发布当前篇")
        self.publish_btn.setFixedHeight(44)
        self.publish_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.publish_btn.clicked.connect(self._on_publish)
        action_grid.addWidget(self.publish_btn, 1, 0)

        # 提示文字替代原来永远禁用的按钮
        self.publish_hint_label = QLabel("9版用于挑选")
        self.publish_hint_label.setFixedHeight(44)
        self.publish_hint_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self.publish_hint_label.setAlignment(Qt.AlignCenter)
        action_grid.addWidget(self.publish_hint_label, 1, 1)

        # 重新生成按钮（生成完成后可见）
        self.regenerate_content_btn = PushButton("重新生成文案")
        self.regenerate_content_btn.setFixedHeight(40)
        self.regenerate_content_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.regenerate_content_btn.setToolTip("仅重新生成当前篇的文案，保留图片")
        self.regenerate_content_btn.clicked.connect(self._on_regenerate_content)
        self.regenerate_content_btn.hide()
        action_grid.addWidget(self.regenerate_content_btn, 2, 0)

        self.regenerate_images_btn = PushButton("重新生成图片")
        self.regenerate_images_btn.setFixedHeight(40)
        self.regenerate_images_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.regenerate_images_btn.setToolTip("重新生成商品图片，保留文案")
        self.regenerate_images_btn.clicked.connect(self._on_regenerate_images)
        self.regenerate_images_btn.hide()
        action_grid.addWidget(self.regenerate_images_btn, 2, 1)

        action_grid.setColumnStretch(0, 3)
        action_grid.setColumnStretch(1, 2)
        right_layout.addLayout(action_grid)

        splitter.addWidget(right_card)
        splitter.setSizes([400, 600])
        layout.addWidget(splitter)
        self._refresh_metrics()

    # ============================================================
    # 数据设置
    # ============================================================

    def _new_image_slots(self):
        return [
            {
                "index": i,
                "label": self.IMAGE_STYLE_LABELS[i],
                "status": "pending",
                "path": "",
                "error": "",
            }
            for i in range(3)
        ]

    def _render_all_image_slots(self):
        for i in range(3):
            self._render_image_slot(i)
        self._update_generated_images_from_slots()
        self._update_retry_button()

    def _truncate(self, text: str, limit: int = 42) -> str:
        text = (text or "").replace("\n", " ").strip()
        return text[:limit] + ("…" if len(text) > limit else "")

    def _refresh_metrics(self):
        if not hasattr(self, "metrics_label"):
            return
        title = self.title_edit.text()
        content = self.content_edit.toPlainText()
        tags = self.tags_edit.text()
        title_len = len(title)
        content_len = len(content)
        tag_count = len([part for part in tags.split() if part.strip()])
        self.metrics_label.setText(f"标题 {title_len}/20 · 正文 {content_len}/1000 · 标签 {tag_count}")
        self.metrics_label.setStyleSheet(
            f"color: {ERROR if title_len > 20 or content_len > 1000 else TEXT_MUTED};"
        )
        if hasattr(self, "preview_title_label"):
            self.preview_title_label.setText(title or "标题预览")
            preview_content = content or "正文预览"
            self.preview_content_label.setText(self._truncate(preview_content, 160))
            self.preview_tags_label.setText(tags)
        if self._posts and 0 <= self._current_post_idx < len(self._posts):
            self._posts[self._current_post_idx]["title"] = title
            self._posts[self._current_post_idx]["content"] = content
            self._posts[self._current_post_idx]["tags"] = tags

    def _set_active_step(self, step_key: str | None):
        active_index = -1
        for idx, (key, _) in enumerate(self.STEP_ORDER):
            if key == step_key:
                active_index = idx
                break
        for idx, label in enumerate(getattr(self, "_step_labels", [])):
            if active_index >= 0 and idx <= active_index:
                label.setStyleSheet(
                    f"background: {PRIMARY}; color: white; border: 1px solid {PRIMARY}; "
                    "border-radius: 8px; padding: 6px 10px; font-weight: 700;"
                )
            else:
                label.setStyleSheet(
                    f"background: {SURFACE_ALT}; color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; "
                    "border-radius: 8px; padding: 6px 10px;"
                )

    def _render_image_slot(self, index: int):
        if index < 0 or index >= len(self.img_previews):
            return
        if not self._image_slots:
            self._image_slots = self._new_image_slots()

        slot = self._image_slots[index]
        label = self.img_previews[index]
        label.clear()

        status = slot.get("status", "pending")
        path = slot.get("path", "")

        if status == "image" and path:
            # 使用异步加载器
            placeholder = _create_placeholder_pixmap(200, 260, "加载中...")
            label.setPixmap(placeholder)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                f"background: {SURFACE_ALT}; border: 1px solid {BORDER}; "
                f"border-radius: 8px; font-size: 13px; color: {TEXT_MUTED};"
            )
            label.setToolTip(path)
            self._image_loader.load_single(index, path, 200, 260)
            return

        if slot.get("status") == "failed":
            error_text = slot.get("error", "")
            from src.utils.error_messages import is_cloudflare_error
            if is_cloudflare_error(error_text):
                label.setText("ChatGPT 被拦截\n检查代理 / 点击重试")
            else:
                label.setText("生成失败\n点击重试")
            label.setToolTip(error_text or "生成失败，请重试")
            # TODO: replace hardcoded #fff7f8 with theme constant (e.g. ERROR_BG) once added to theme.py
            label.setStyleSheet(
                f"background: #fff7f8; border: 1px solid {ERROR}; "
                f"border-radius: 8px; font-size: 13px; color: {ERROR};"
            )
        else:
            label.setText("等待生成...")
            label.setToolTip("")
            label.setStyleSheet(placeholder_style())

    def _on_image_loaded(self, index: int, path: str, pixmap):
        """异步图片加载完成回调"""
        if 0 <= index < len(self.img_previews):
            self.img_previews[index].setPixmap(pixmap)

    def _update_generated_images_from_slots(self):
        self._generated_images = [
            slot.get("path", "")
            for slot in self._image_slots
            if slot.get("status") == "image"
            and slot.get("path")
            and os.path.exists(slot.get("path", ""))
        ]

    def _missing_image_indices(self):
        missing = []
        for i, slot in enumerate(self._image_slots):
            path = slot.get("path", "")
            if slot.get("status") != "image" or not path or not os.path.exists(path):
                missing.append(i)
        return missing

    def _update_retry_button(self):
        if not hasattr(self, "retry_images_btn"):
            return
        missing = self._missing_image_indices() if self._image_slots else []
        should_show = self._has_image_attempt and bool(missing) and not self._is_generating
        self.retry_images_btn.setVisible(should_show)
        self.retry_images_btn.setEnabled(should_show and not self._is_retrying_images)

    def _show_product_reference(self):
        local_imgs = self._product.get("local_images", []) if self._product else []
        if local_imgs and os.path.exists(local_imgs[0]):
            self._image_loader.load_single(0, local_imgs[0], 200, 260)

    def set_product(self, product: dict):
        self._product = product
        self._generated_images = []
        self._image_slots = self._new_image_slots()
        self._saved_note_ids = []
        self._has_image_attempt = False
        self._is_retrying_images = False
        self._posts = []
        self._directions = []
        self._current_post_idx = 0
        self.direction_combo.clear()
        self.product_name_label.setText(product.get("title", "未命名"))
        self.title_edit.clear()
        self.content_edit.clear()
        self.tags_edit.clear()
        self.direction_info_card.hide()
        self.post_index_label.setText("")
        self.total_label.setText("")
        self.post_nav_label.setText("")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)

        self._render_all_image_slots()
        self._show_product_reference()

    def get_product(self) -> dict | None:
        """获取当前产品数据（替代直接访问 _product）"""
        return self._product

    def set_images(self, image_paths: list):
        """Display 3 generated images"""
        self._has_image_attempt = True
        results = []
        for i in range(3):
            path = image_paths[i] if i < len(image_paths) else ""
            if path and os.path.exists(path):
                results.append({
                    "index": i,
                    "status": "image",
                    "path": path,
                    "error": "",
                })
            else:
                results.append({
                    "index": i,
                    "status": "failed",
                    "path": "",
                    "error": "未生成图片",
                })
        self.set_image_results(results)

    def set_image_results(self, results: list):
        """Set image slot results after a full generation run."""
        self._has_image_attempt = True
        self._image_slots = self._new_image_slots()
        seen = set()
        for result in results or []:
            idx = int(result.get("index", len(seen)))
            if 0 <= idx < 3:
                self._image_slots[idx].update({
                    "status": result.get("status", "failed"),
                    "path": result.get("path", "") or "",
                    "error": result.get("error", "") or "",
                })
                seen.add(idx)
        for i in range(3):
            if i not in seen:
                self._image_slots[i].update({
                    "status": "failed",
                    "path": "",
                    "error": "未生成图片",
                })
        self._render_all_image_slots()

    def update_image_results(self, results: list):
        """Merge image slot results from retry generation."""
        if not self._image_slots:
            self._image_slots = self._new_image_slots()
        self._has_image_attempt = True
        for result in results or []:
            idx = int(result.get("index", -1))
            if 0 <= idx < 3:
                self._image_slots[idx].update({
                    "status": result.get("status", "failed"),
                    "path": result.get("path", "") or "",
                    "error": result.get("error", "") or "",
                })
                self._render_image_slot(idx)
        self._is_retrying_images = False
        self._update_generated_images_from_slots()
        self._update_retry_button()

    def set_image_slots_pending(self, indices: list):
        if not self._image_slots:
            self._image_slots = self._new_image_slots()
        self._has_image_attempt = True
        self._is_retrying_images = True
        for idx in indices:
            if 0 <= idx < 3:
                self._image_slots[idx].update({
                    "status": "pending",
                    "path": "",
                    "error": "",
                })
                self._render_image_slot(idx)
        self._update_generated_images_from_slots()
        self._update_retry_button()

    def get_missing_image_indices(self) -> list:
        return self._missing_image_indices()

    def get_generated_images(self) -> list:
        self._update_generated_images_from_slots()
        images = self._generated_images.copy()
        # 如果AI生成的图片不够，用产品原图兜底
        if not images and self._product:
            local_imgs = self._product.get("local_images", [])
            for img in local_imgs:
                if img and os.path.exists(img):
                    images.append(img)
                    break
        return images

    def set_saved_note_ids(self, note_ids: list):
        self._saved_note_ids = note_ids or []

    def get_saved_note_ids(self) -> list:
        return self._saved_note_ids.copy()

    def _on_image_clicked(self, index: int):
        if not self._image_slots or index < 0 or index >= len(self._image_slots):
            return
        slot = self._image_slots[index]
        path = slot.get("path", "")
        if slot.get("status") == "image" and path and os.path.exists(path):
            self._open_image_dialog(path, slot.get("label", "图片"))
        elif slot.get("status") == "failed" and not self._is_retrying_images:
            self.retry_images_clicked.emit([index])

    def _open_image_dialog(self, path: str, title: str):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            InfoBar.warning("无法打开图片", "图片文件无法读取", parent=self)
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(16, 16, 16, 16)
        dialog_layout.setSpacing(12)

        screen = QApplication.primaryScreen().availableGeometry()
        max_width = int(screen.width() * 0.75)
        max_height = int(screen.height() * 0.75)
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setPixmap(pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        dialog_layout.addWidget(image_label)

        path_label = CaptionLabel(path)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setStyleSheet(f"color: {TEXT_MUTED};")
        dialog_layout.addWidget(path_label)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = PushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(close_btn)
        dialog_layout.addLayout(close_row)

        dialog.resize(min(max_width + 40, screen.width()), min(max_height + 100, screen.height()))
        dialog.exec_()

    def _on_retry_missing_images(self):
        if self._is_retrying_images:
            return
        indices = self.get_missing_image_indices()
        if indices:
            self.retry_images_clicked.emit(indices)

    # ============================================================
    # 商品下拉选择
    # ============================================================

    def showEvent(self, event):
        """切到本页时刷新商品列表"""
        super().showEvent(event)
        try:
            self.load_products()
        except Exception:
            pass

    def load_products(self):
        """从采集目录加载商品列表到下拉框"""
        self.product_combo.blockSignals(True)
        self.product_combo.clear()
        self.product_combo.addItem("— 选择商品 —", userData=None)
        try:
            import json
            from src.services.ai_backend import PRODUCTS_JSON
            if os.path.exists(PRODUCTS_JSON):
                with open(PRODUCTS_JSON, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 兼容 {"products": [...]} 和直接列表两种格式
                raw_list = data if isinstance(data, list) else data.get("products", [])
                for p in raw_list:
                    title = (p.get("title", "") or p.get("name", ""))[:60] or "未命名"
                    display = title[:36] + ("…" if len(title) > 36 else "")
                    self.product_combo.addItem(display, userData=p)
        except Exception as e:
            logging.getLogger("ai_generate_page").warning("Load products failed: %s", e)
        self.product_combo.blockSignals(False)

    def _on_product_combo_changed(self, index: int):
        """商品下拉框切换"""
        if index < 0:
            return
        product = self.product_combo.currentData()
        if product:
            self.set_product(product)

    def set_content(self, title: str, content: str, tags: str):
        self.title_edit.setText(title)
        self.content_edit.setPlainText(content)
        self.tags_edit.setText(tags)
        self._refresh_metrics()

    def set_posts(self, posts: list, directions: list):
        """设置两轮生成的全部结果"""
        self._posts = posts or []
        self._directions = directions or []
        self._current_post_idx = 0

        logger = logging.getLogger("ai_generate_page")
        logger.info("set_posts 被调用: %d 篇文案, %d 个方向", len(self._posts), len(self._directions))

        # 填充方向选择器
        self.direction_combo.blockSignals(True)
        self.direction_combo.clear()
        try:
            if not self._directions:
                logger.warning("方向列表为空，无法填充下拉框")
            else:
                for i, d in enumerate(self._directions):
                    if isinstance(d, dict):
                        label = f"{d.get('id', i+1)} - {d.get('name', '未知')}"
                    else:
                        label = str(d)
                    self.direction_combo.addItem(label)
                    logger.info("添加方向选项: %s", label)
        except Exception as e:
            logger.warning("填充方向选择器失败: %s", e)
        self.direction_combo.blockSignals(False)

        # 确保方向下拉框可见且启用
        self.direction_combo.setVisible(True)
        if self.direction_combo.count() > 0:
            self.direction_combo.setEnabled(True)
            self.direction_combo.setCurrentIndex(0)
            logger.info("方向下拉框已启用，选项数: %d", self.direction_combo.count())
            # 弹出提示让用户知道方向已就绪
            try:
                InfoBar.success(
                    "方向就绪",
                    f"已生成 {self.direction_combo.count()} 个方向，点击「方向」下拉框切换",
                    parent=self,
                    duration=3000,
                )
            except Exception:
                pass
        else:
            self.direction_combo.setEnabled(False)
            logger.warning("方向下拉框无选项，保持禁用")

        # 构建帖子索引面板
        self._build_post_index_panel()

        # 显示第一篇
        if self._posts:
            self._show_post(0)
            self.total_label.setText(f"共 {len(self._posts)} 篇")
        else:
            self.total_label.setText("")

    def _build_post_index_panel(self):
        """构建 3×3 帖子索引面板"""
        # 清空现有内容
        while self._post_index_grid.count():
            item = self._post_index_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, post in enumerate(self._posts):
            row = i // 3
            col = i % 3

            card = QFrame()
            card.setFixedSize(150, 78)
            card.setCursor(Qt.PointingHandCursor)
            card.setStyleSheet(f"""
                QFrame {{
                    background: {SURFACE_ALT};
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    border-color: {PRIMARY};
                    background: {TEXT_SECONDARY}10;
                }}
            """)

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setSpacing(3)

            idx_label = QLabel(f"#{i + 1} · {post.get('direction_name', '') or '方向'}")
            idx_label.setObjectName("indexTitle")
            idx_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY};")
            card_layout.addWidget(idx_label)

            title = self._truncate(post.get("title", "") or "未命名", 18)
            title_label = QLabel(title)
            title_label.setObjectName("indexSummary")
            title_label.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
            card_layout.addWidget(title_label)

            length_label = QLabel(f"{len(post.get('content', '') or '')}字")
            length_label.setObjectName("indexLength")
            length_label.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
            card_layout.addWidget(length_label)

            # 点击事件
            card.mousePressEvent = lambda event, idx=i: self._show_post(idx)

            self._post_index_grid.addWidget(card, row, col)

        self.post_index_panel.setVisible(bool(self._posts))

    def set_generating(self, generating: bool):
        self._is_generating = generating
        self.generate_btn.setEnabled(not generating)
        self.publish_btn.setEnabled(not generating)

        # Lock editors and controls during generation
        self.title_edit.setEnabled(not generating)
        self.content_edit.setEnabled(not generating)
        self.tags_edit.setEnabled(not generating)
        self.style_combo.setEnabled(not generating)
        self.model_combo.setEnabled(not generating)
        self.save_btn.setEnabled(not generating)

        if generating:
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.progress_bar.show()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(12)
            self._set_active_step("direction_generating")
            self.status_label.setText("正在生成方向、文案和图片...")
            self.status_label.show()
            # 生成中隐藏重新生成按钮
            self.regenerate_content_btn.hide()
            self.regenerate_images_btn.hide()
        else:
            # Re-enable nav buttons only if there are posts to navigate
            has_posts = bool(self._posts)
            self.prev_btn.setEnabled(has_posts and self._current_post_idx > 0)
            self.next_btn.setEnabled(has_posts and self._current_post_idx < len(self._posts) - 1)
            self.progress_bar.hide()
            self.status_label.hide()
            self._set_active_step("completed" if self._posts else None)
            # 生成完成且有内容时，显示重新生成按钮
            has_content = bool(self._posts)
            self.regenerate_content_btn.setVisible(has_content)
            self.regenerate_content_btn.setEnabled(has_content)
            self.regenerate_images_btn.setVisible(has_content)
            self.regenerate_images_btn.setEnabled(has_content)
        self._update_retry_button()

    def set_step(self, step_key: str, step_label: str):
        """更新当前步骤状态显示"""
        if step_key == "completed":
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self._set_active_step("completed")
            InfoBar.success("完成", "生成完成", parent=self)
            self.status_label.hide()
        elif step_key == "failed":
            self._set_active_step(None)
            InfoBar.error("错误", "生成失败", parent=self)
            self.status_label.hide()
        else:
            progress_map = {
                "direction_generating": 25,
                "image_generating": 50,
                "content_generating": 75,
            }
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(progress_map.get(step_key, 35))
            self._set_active_step(step_key)
            self.status_label.setText(step_label)
            self.status_label.setStyleSheet(f"color: {INFO}; font-size: 13px;")
            self.status_label.show()

    # ============================================================
    # 帖子导航
    # ============================================================

    def _save_current_post(self):
        """将当前编辑器内容回写到 _posts，防止切换帖子时丢失修改"""
        if not self._posts or self._current_post_idx < 0 or self._current_post_idx >= len(self._posts):
            return
        post = self._posts[self._current_post_idx]
        post["title"] = self.title_edit.text()
        post["content"] = self.content_edit.toPlainText()
        post["tags"] = self.tags_edit.text()

    def _show_post(self, idx: int):
        """显示指定索引的帖子"""
        if not self._posts or idx < 0 or idx >= len(self._posts):
            return

        # 先保存当前帖子的编辑内容
        self._save_current_post()

        self._current_post_idx = idx
        post = self._posts[idx]

        # 更新编辑器
        self.title_edit.setText(post.get("title", ""))
        self.content_edit.setPlainText(post.get("content", ""))
        self.tags_edit.setText(post.get("tags", ""))
        self._refresh_metrics()

        # 更新帖子序号
        dir_id = post.get("direction_id", "?")
        dir_name = post.get("direction_name", "")
        hook = post.get("hook_style", "")
        self.post_index_label.setText(f"#{idx + 1} | 方向{dir_id} · {dir_name} · {hook}")

        # 更新方向选择器高亮
        for i, d in enumerate(self._directions):
            if d["id"] == dir_id:
                self.direction_combo.blockSignals(True)
                self.direction_combo.setCurrentIndex(i)
                self.direction_combo.blockSignals(False)
                break

        # 更新方向信息卡片
        self._update_direction_info(dir_id)

        # 更新导航按钮状态
        self.prev_btn.setEnabled(idx > 0)
        self.next_btn.setEnabled(idx < len(self._posts) - 1)

        # 高亮当前方向的所有帖子
        dir_posts = [i for i, p in enumerate(self._posts) if p.get("direction_id") == dir_id]
        local_idx = dir_posts.index(idx) + 1 if idx in dir_posts else 0
        self.post_nav_label.setText(f"方向{dir_id} 第{local_idx}/{len(dir_posts)}篇 | 总 {idx + 1}/{len(self._posts)}")

        # 更新索引面板高亮
        self._update_post_index_highlight(idx)

    def _update_post_index_highlight(self, active_idx: int):
        """更新帖子索引面板的高亮状态"""
        for i in range(self._post_index_grid.count()):
            item = self._post_index_grid.itemAt(i)
            if item and item.widget():
                card = item.widget()
                if i == active_idx:
                    card.setStyleSheet(f"""
                        QFrame {{
                            background: {PRIMARY};
                            border: 1px solid {PRIMARY};
                            border-radius: 6px;
                        }}
                        QFrame QLabel {{
                            color: #ffffff;
                        }}
                    """)
                    # 更新子标签颜色
                    for j in range(card.layout().count()):
                        child = card.layout().itemAt(j)
                        if child and child.widget():
                            child.widget().setStyleSheet(
                                child.widget().styleSheet().replace(TEXT_PRIMARY, "#ffffff").replace(TEXT_MUTED, "#ffffffcc")
                            )
                else:
                    card.setStyleSheet(f"""
                        QFrame {{
                            background: {SURFACE_ALT};
                            border: 1px solid {BORDER};
                            border-radius: 6px;
                        }}
                        QFrame:hover {{
                            border-color: {PRIMARY};
                            background: {TEXT_SECONDARY}10;
                        }}
                    """)
                    for j in range(card.layout().count()):
                        child = card.layout().itemAt(j)
                        if not child or not child.widget():
                            continue
                        widget = child.widget()
                        if widget.objectName() == "indexTitle":
                            widget.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY};")
                        elif widget.objectName() == "indexSummary":
                            widget.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
                        elif widget.objectName() == "indexLength":
                            widget.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")

    def _update_direction_info(self, dir_id: str):
        """更新方向信息卡片"""
        for d in self._directions:
            if d["id"] == dir_id:
                self.dir_name_label.setText(d["name"])
                self.dir_audience_label.setText(f"目标人群：{d.get('target_audience', '-')}")
                self.dir_angle_label.setText(f"内容角度：{d.get('angle', '-')}")
                self.dir_hook_label.setText(f"钩子类型：{d.get('hook_type', '-')}")
                self.direction_info_card.show()
                return
        self.direction_info_card.hide()

    def _on_direction_changed(self, index: int):
        """方向切换时，跳到该方向的第一篇"""
        if not self._directions or index < 0 or index >= len(self._directions):
            return
        try:
            dir_id = self._directions[index]["id"]
            for i, p in enumerate(self._posts):
                if p.get("direction_id") == dir_id:
                    self._show_post(i)
                    return
        except Exception as e:
            logging.getLogger("ai_generate_page").warning("方向切换失败: %s", e)

    def _prev_post(self):
        if self._current_post_idx > 0:
            self._show_post(self._current_post_idx - 1)

    def _next_post(self):
        if self._current_post_idx < len(self._posts) - 1:
            self._show_post(self._current_post_idx + 1)

    def _on_prompt_edit(self):
        """跳转去设置页编辑提示词"""
        self.prompt_edit_requested.emit()

    def _on_template_changed(self, index: int):
        """模板下拉框切换时，更新编辑按钮状态"""
        key = self.template_combo.currentData() or ""
        self.edit_template_btn.setEnabled(bool(key))

    def _on_edit_template(self):
        """弹窗编辑当前选中的文案模板"""
        key = self.template_combo.currentData() or ""
        if not key:
            return
        from src.gui.widgets.template_edit_dialog import TemplateEditDialog
        current_text = TemplateEditDialog.get_template_text(key)
        dialog = TemplateEditDialog(key, current_text, parent=self)
        dialog.exec_()

    # ============================================================
    # 按钮事件
    # ============================================================

    def _refresh_model_list(self):
        """从 API Key Manager 加载可用模型列表"""
        self.model_combo.clear()
        self._model_entries = []  # 存储模型信息
        try:
            from src.ai.api_key_manager import get_key_manager
            km = get_key_manager()
            seen = set()
            for entry in km._keys:
                if not entry.enabled or entry.error_count >= entry.max_errors:
                    continue
                label = f"{entry.provider.value}/{entry.model}"
                key = f"{entry.provider.value}:{entry.model}"
                if key in seen:
                    continue
                seen.add(key)
                self._model_entries.append({
                    "provider": entry.provider.value,
                    "model": entry.model,
                    "base_url": entry.base_url,
                })
                self.model_combo.addItem(label)
        except Exception:
            self._model_entries = [{"provider": None, "model": None, "base_url": None}]
            self.model_combo.addItem("默认模型")

    def _get_selected_model(self):
        """获取当前选中的模型信息"""
        idx = self.model_combo.currentIndex()
        if 0 <= idx < len(self._model_entries):
            return self._model_entries[idx]
        return {"provider": None, "model": None, "base_url": None}

    def _on_generate(self):
        if not self._product:
            InfoBar.warning("提示", "请先在顶部「商品」下拉框选择商品", parent=self)
            return
        # 获取选中的模型信息
        model_data = self._get_selected_model()
        # 获取选中的文案模板
        template_key = self.template_combo.currentData() or ""
        # 构建生成参数
        gen_params = {
            "product": self._product,
            "style": self.style_combo.currentText(),
            "model_provider": model_data.get("provider"),
            "model_name": model_data.get("model"),
            "content_template_key": template_key,
        }
        # 如果有搜索结果，添加到参数中
        if self._search_results_text:
            gen_params["search_results"] = self._search_results_text
            # 使用后清空，避免下次生成时重复使用
            self._search_results = []
            self._search_results_text = ""
        self.generate_clicked.emit(gen_params)

    def _on_save(self):
        # 保存当前帖子的编辑内容
        current_post = {}
        if self._posts and 0 <= self._current_post_idx < len(self._posts):
            current_post = self._posts[self._current_post_idx]
            current_post["title"] = self.title_edit.text()
            current_post["content"] = self.content_edit.toPlainText()
            current_post["tags"] = self.tags_edit.text()

        self.save_clicked.emit({
            "note_id": self._saved_note_ids[self._current_post_idx] if self._current_post_idx < len(self._saved_note_ids) else None,
            "title": self.title_edit.text(),
            "content": self.content_edit.toPlainText(),
            "tags": self.tags_edit.text(),
            "images": self.get_generated_images(),
            "product_name": self._product.get("title", "") if self._product else "",
            "direction_id": current_post.get("direction_id", ""),
            "direction_name": current_post.get("direction_name", ""),
            "variants": self._posts,
            "selected_variant_index": self._current_post_idx,
        })
        InfoBar.success("保存成功", "当前文案已保存", parent=self)

    def _on_publish(self):
        title = self.title_edit.text()
        content = self.content_edit.toPlainText()
        if not title or not content:
            InfoBar.warning("提示", "请先生成内容再发布", parent=self)
            return
        current_post = {}
        if self._posts and 0 <= self._current_post_idx < len(self._posts):
            current_post = self._posts[self._current_post_idx]
            current_post["title"] = title
            current_post["content"] = content
            current_post["tags"] = self.tags_edit.text()
        self.publish_clicked.emit({
            "note_id": self._saved_note_ids[self._current_post_idx] if self._current_post_idx < len(self._saved_note_ids) else None,
            "title": title,
            "content": content,
            "tags": self.tags_edit.text(),
            "images": self.get_generated_images(),
            "product_name": self._product.get("title", "") if self._product else "",
            "direction_id": current_post.get("direction_id", ""),
            "direction_name": current_post.get("direction_name", ""),
            "variants": self._posts,
            "selected_variant_index": self._current_post_idx,
        })

    def _on_publish_all(self):
        """9 versions are alternatives; only the selected version can be queued."""
        InfoBar.info("提示", "9 个版本是备选，请选择一个当前篇发布", parent=self)

    def _on_regenerate_content(self):
        """仅重新生成当前方向文案（3 篇），保留图片"""
        if not self._product or not self._posts:
            InfoBar.warning("提示", "请先生成内容", parent=self)
            return
        model_data = self._get_selected_model()
        template_key = self.template_combo.currentData() or ""
        current_post = self._posts[self._current_post_idx] if 0 <= self._current_post_idx < len(self._posts) else {}
        direction_id = current_post.get("direction_id", "")
        # 从 self._directions 里找到完整的 direction 数据
        direction_data = {}
        for d in self._directions:
            if d.get("id") == direction_id:
                direction_data = d
                break
        if not direction_data:
            InfoBar.warning("提示", "未找到方向数据，无法重新生成", parent=self)
            return
        self.regenerate_content_clicked.emit({
            "product": self._product,
            "direction_data": direction_data,
            "style": self.style_combo.currentText(),
            "model_provider": model_data.get("provider"),
            "model_name": model_data.get("model"),
            "content_template_key": template_key,
            "current_post_idx": self._current_post_idx,
        })

    # ============================================================
    # 热点主题推荐
    # ============================================================

    def _on_open_hot_topics(self):
        """打开热点主题弹窗"""
        from src.gui.widgets.hot_topic_dialog import HotTopicDialog
        dialog = HotTopicDialog(self)
        dialog.topic_selected.connect(self._on_hot_topic_selected)
        dialog.exec_()

    def _on_hot_topic_selected(self, topic: str):
        """热点主题被选中：填入并触发生成"""
        fake_product = {
            "title": topic,
            "description": topic,
            "price": "",
            "local_images": [],
        }
        self.set_product(fake_product)
        self._on_generate()


    # ============================================================
    # URL 内容提取
    # ============================================================

    def _on_open_url_extract(self):
        """打开 URL 提取弹窗"""
        from src.gui.widgets.url_extract_dialog import URLExtractDialog
        dialog = URLExtractDialog(self)
        dialog.topic_extracted.connect(self._on_url_topic_extracted)
        dialog.exec_()

    def _on_url_topic_extracted(self, topic: str):
        """URL 提炼的主题被选中"""
        fake_product = {
            'title': topic,
            'description': topic,
            'price': '',
            'local_images': [],
        }
        self.set_product(fake_product)
        self._on_generate()

    # ============================================================
    # 搜索资料集成
    # ============================================================

    def _on_open_search(self):
        """打开搜索资料弹窗"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QLabel, QMessageBox, QProgressBar
        from src.ai.search_integration import SearchWorker, format_search_results_for_prompt

        dialog = QDialog(self)
        dialog.setWindowTitle("搜索资料")
        dialog.setMinimumSize(600, 500)

        layout = QVBoxLayout(dialog)

        # 搜索输入
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("搜索关键词:"))
        query_edit = QLineEdit()
        query_edit.setPlaceholderText("输入关键词，如：2024年配饰流行趋势")
        input_layout.addWidget(query_edit)
        search_btn = QPushButton("搜索")
        input_layout.addWidget(search_btn)
        layout.addLayout(input_layout)

        # 进度条（搜索时显示）
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)  # 无限循环模式
        progress_bar.hide()
        layout.addWidget(progress_bar)

        # 搜索结果展示
        layout.addWidget(QLabel("搜索结果:"))
        result_edit = QTextEdit()
        result_edit.setReadOnly(True)
        result_edit.setPlaceholderText("搜索结果将显示在这里...")
        layout.addWidget(result_edit)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        use_btn = QPushButton("使用这些资料")
        use_btn.setEnabled(False)
        cancel_btn = QPushButton("取消")
        btn_layout.addWidget(use_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        # 存储搜索结果
        search_results = []

        def on_search_finished(results):
            """搜索完成回调"""
            progress_bar.hide()
            search_btn.setEnabled(True)

            if results:
                search_results.clear()
                search_results.extend(results)
                formatted = format_search_results_for_prompt(results)
                result_edit.setText(formatted)
                use_btn.setEnabled(True)
            else:
                result_edit.setText("未找到相关结果，请尝试其他关键词")
                use_btn.setEnabled(False)

        def do_search():
            """执行搜索（后台线程）"""
            query = query_edit.text().strip()
            if not query:
                QMessageBox.warning(dialog, "提示", "请输入搜索关键词")
                return

            result_edit.clear()
            progress_bar.show()
            search_btn.setEnabled(False)
            use_btn.setEnabled(False)

            # 使用 SearchWorker 后台搜索
            worker = SearchWorker(query, callback=on_search_finished)
            worker.start()

        def use_results():
            """使用搜索结果"""
            if not search_results:
                QMessageBox.warning(dialog, "提示", "请先搜索获取资料")
                return

            # 存储搜索结果到页面属性
            self._search_results = search_results
            self._search_results_text = format_search_results_for_prompt(search_results)

            # 更新搜索按钮文本，显示已加载资料
            self.search_btn.setText("✓ 已加载资料")
            self.search_btn.setToolTip("已加载搜索资料，生成时将自动使用")

            dialog.accept()

        search_btn.clicked.connect(do_search)
        use_btn.clicked.connect(use_results)
        cancel_btn.clicked.connect(dialog.reject)

        dialog.exec_()

    def _on_regenerate_images(self):
        """重新生成当前商品的图片，保留文案"""
        if not self._product:
            InfoBar.warning("提示", "请先选择商品", parent=self)
            return
        existing = self.get_generated_images()
        self.regenerate_images_clicked.emit({
            "product": self._product,
            "existing_images": existing,
        })
