"""
AI Generate Page - 两轮生成：方向 → 文案（3方向 × 3篇 = 9篇）
"""
import os
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget, QLabel, QSizePolicy,
    QScrollArea, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, PlainTextEdit,
    LineEdit, ComboBox, ProgressBar, InfoBar, StrongBodyLabel,
    BodyLabel, CaptionLabel,
)
from src.gui.styles.theme import (
    BORDER,
    ERROR,
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

    IMAGE_STYLE_LABELS = ["博主风", "纯白简约", "氛围场景"]

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
        self._image_loader = AsyncImageLoader(self)
        self._image_loader.image_loaded.connect(self._on_image_loaded)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGINS)
        layout.setSpacing(16)

        # ===== Header: 标题 + 方向/帖子导航 =====
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel("AI 内容生成")
        title.setStyleSheet(page_title_style())
        title_box.addWidget(title)
        subtitle = QLabel("一个商品生成 9 个文案版本，发布管理只保存当前选中的 1 篇。")
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

        self.prev_btn = PushButton("◀")
        self.prev_btn.setFixedSize(36, 32)
        self.prev_btn.clicked.connect(self._prev_post)
        header.addWidget(self.prev_btn)

        self.next_btn = PushButton("▶")
        self.next_btn.setFixedSize(36, 32)
        self.next_btn.clicked.connect(self._next_post)
        header.addWidget(self.next_btn)

        header.addStretch()

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

        # ===== Status label (生成中显示) =====
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        # ===== Main content area =====
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        # ===== Left: 3 image previews + post index panel =====
        left_card = CardWidget(self)
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
        content_layout.addWidget(left_card, stretch=1)

        # ===== Right: editor =====
        right_card = CardWidget(self)
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
        right_layout.addWidget(self.title_edit)

        # 正文
        right_layout.addWidget(BodyLabel("正文:"))
        self.content_edit = PlainTextEdit()
        self.content_edit.setPlaceholderText("AI生成的文案...")
        right_layout.addWidget(self.content_edit)

        # 话题标签
        right_layout.addWidget(BodyLabel("话题标签:"))
        self.tags_edit = LineEdit()
        self.tags_edit.setPlaceholderText("#话题1 #话题2 #话题3")
        self.tags_edit.setFixedHeight(40)
        right_layout.addWidget(self.tags_edit)

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

        action_grid.setColumnStretch(0, 3)
        action_grid.setColumnStretch(1, 2)
        right_layout.addLayout(action_grid)

        content_layout.addWidget(right_card, stretch=2)
        layout.addLayout(content_layout)

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
            label.setText("生成失败\n点击重试")
            label.setToolTip(slot.get("error", "生成失败，请重试"))
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
        return self._generated_images.copy()

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

    def set_content(self, title: str, content: str, tags: str):
        self.title_edit.setText(title)
        self.content_edit.setPlainText(content)
        self.tags_edit.setText(tags)

    def set_posts(self, posts: list, directions: list):
        """设置两轮生成的全部结果"""
        self._posts = posts
        self._directions = directions
        self._current_post_idx = 0

        # 填充方向选择器
        self.direction_combo.blockSignals(True)
        self.direction_combo.clear()
        for d in directions:
            label = f"{d['id']} - {d['name']}"
            self.direction_combo.addItem(label)
        self.direction_combo.blockSignals(False)

        # 构建帖子索引面板
        self._build_post_index_panel()

        # 显示第一篇
        if posts:
            self._show_post(0)
            self.total_label.setText(f"共 {len(posts)} 篇")
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
            card.setFixedSize(80, 60)
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
            card_layout.setContentsMargins(4, 4, 4, 4)
            card_layout.setSpacing(2)

            idx_label = QLabel(f"#{i + 1}")
            idx_label.setAlignment(Qt.AlignCenter)
            idx_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY};")
            card_layout.addWidget(idx_label)

            dir_id = post.get("direction_id", "?")
            dir_label = QLabel(f"D{dir_id}")
            dir_label.setAlignment(Qt.AlignCenter)
            dir_label.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
            card_layout.addWidget(dir_label)

            # 点击事件
            card.mousePressEvent = lambda event, idx=i: self._show_post(idx)

            self._post_index_grid.addWidget(card, row, col)

        self.post_index_panel.setVisible(bool(self._posts))

    def set_generating(self, generating: bool):
        self._is_generating = generating
        self.generate_btn.setEnabled(not generating)
        self.publish_btn.setEnabled(not generating)
        if generating:
            self.progress_bar.show()
            self.progress_bar.setRange(0, 0)
            self.status_label.setText("正在生成方向、文案和图片...")
            self.status_label.show()
        else:
            self.progress_bar.hide()
            self.status_label.hide()
        self._update_retry_button()

    # ============================================================
    # 帖子导航
    # ============================================================

    def _show_post(self, idx: int):
        """显示指定索引的帖子"""
        if not self._posts or idx < 0 or idx >= len(self._posts):
            return

        self._current_post_idx = idx
        post = self._posts[idx]

        # 更新编辑器
        self.title_edit.setText(post.get("title", ""))
        self.content_edit.setPlainText(post.get("content", ""))
        self.tags_edit.setText(post.get("tags", ""))

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
        dir_id = self._directions[index]["id"]
        for i, p in enumerate(self._posts):
            if p.get("direction_id") == dir_id:
                self._show_post(i)
                return

    def _prev_post(self):
        if self._current_post_idx > 0:
            self._show_post(self._current_post_idx - 1)

    def _next_post(self):
        if self._current_post_idx < len(self._posts) - 1:
            self._show_post(self._current_post_idx + 1)

    # ============================================================
    # 按钮事件
    # ============================================================

    def _on_generate(self):
        if not self._product:
            InfoBar.warning("提示", "请先从任务列表选择产品", parent=self)
            return
        self.generate_clicked.emit({
            "product": self._product,
            "style": self.style_combo.currentText(),
        })

    def _on_save(self):
        # 保存当前帖子的编辑内容
        current_post = {}
        if self._posts and 0 <= self._current_post_idx < len(self._posts):
            current_post = self._posts[self._current_post_idx]
            current_post["title"] = self.title_edit.text()
            current_post["content"] = self.content_edit.toPlainText()
            current_post["tags"] = self.tags_edit.text()

        self.save_clicked.emit({
            "note_id": self._saved_note_ids[0] if self._saved_note_ids else None,
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
            "note_id": self._saved_note_ids[0] if self._saved_note_ids else None,
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
