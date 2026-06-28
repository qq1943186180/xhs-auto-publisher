"""
Task List Page - with auto-load after collection
"""
import json
import os
import subprocess
import sys
import logging
import requests
from pathlib import Path
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel, QTableWidgetItem, QFrame, QMessageBox
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QByteArray, QBuffer
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PIL import Image as PILImage
import io

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, TableWidget,
    CheckBox, InfoBar
)
from src.gui.styles.theme import (
    BORDER,
    INFO,
    PRIMARY,
    PRIMARY_LIGHT,
    SUCCESS,
    SURFACE_ALT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    page_subtitle_style,
    page_title_style,
)
from src.gui.utils import PAGE_MARGINS, status_label
from src.gui.widgets.status_badge import StatusBadge
from src.utils.logger import get_logger

logger = get_logger("gui.task_list_page")

COLLECTED_DIR = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "collected")
PRODUCTS_JSON = os.path.join(COLLECTED_DIR, "products_simple.json")
CONFIG_JSON = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "config.json")
IMAGES_PER_PRODUCT = 5


class TaskListPage(QWidget):
    """Task list page"""

    generate_requested = pyqtSignal(list)
    product_selected = pyqtSignal(dict)
    collect_done = pyqtSignal()
    draft_edit_requested = pyqtSignal(int)
    draft_publish_requested = pyqtSignal(int)

    @staticmethod
    def _load_image_to_pixmap(img_path: str, width: int, height: int):
        """
        加载图片并返回缩放后的 QPixmap
        优先用 QImage（快），失败则用 Pillow（支持 WEBP 等格式）
        """
        # 先试 QImage（支持 PNG/JPG/BMP）
        image = QImage(img_path)
        if not image.isNull():
            return QPixmap.fromImage(image).scaled(
                width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        # QImage 不支持此格式（如 WEBP），用 Pillow 转
        try:
            pil_img = PILImage.open(img_path)
            if pil_img.mode in ('RGBA', 'P', 'LA', 'L'):
                pil_img = pil_img.convert('RGB')
            # Pillow -> QImage -> QPixmap
            from io import BytesIO
            buf = BytesIO()
            pil_img.save(buf, format='JPEG', quality=95)
            buf.seek(0)
            qimg = QImage()
            qimg.loadFromData(buf.getvalue())
            if not qimg.isNull():
                return QPixmap.fromImage(qimg).scaled(
                    width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
        except Exception as e:
            logger.warning("Pillow 加载失败: %s (%s)", img_path, e)
        return None

    @staticmethod
    def _load_image_from_url(url: str, width: int, height: int):
        """
        从 URL 加载图片并返回缩放后的 QPixmap
        用于 local_images 为空时，直接从图片 URL 加载
        """
        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            if resp.status_code == 200:
                pil_img = PILImage.open(io.BytesIO(resp.content))
                if pil_img.mode in ('RGBA', 'P', 'LA', 'L'):
                    pil_img = pil_img.convert('RGB')
                buf = io.BytesIO()
                pil_img.save(buf, format='JPEG', quality=95)
                buf.seek(0)
                qimg = QImage()
                qimg.loadFromData(buf.getvalue())
                if not qimg.isNull():
                    return QPixmap.fromImage(qimg).scaled(
                        width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
        except Exception as e:
            logger.warning("URL 图片加载失败: %s (%s)", url[:50], e)
        return None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._products = []
        self._collect_process = None
        self._collect_process_started = False  # 进程互斥标志
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._check_collect_done)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGINS)
        layout.setSpacing(16)

        # Title
        title_row = QVBoxLayout()
        title_row.setSpacing(4)
        title = QLabel("任务列表")
        title.setStyleSheet(page_title_style())
        title_row.addWidget(title)
        subtitle = QLabel("采集商品素材，并选择需要生成内容的产品。")
        subtitle.setStyleSheet(page_subtitle_style())
        title_row.addWidget(subtitle)
        layout.addLayout(title_row)

        # Workflow stepper
        self.workflow_card = CardWidget(self)
        workflow_layout = QHBoxLayout(self.workflow_card)
        workflow_layout.setContentsMargins(16, 12, 16, 12)
        workflow_layout.setSpacing(10)
        self._workflow_labels = []
        for i, step in enumerate(("1 采集", "2 选品", "3 生成", "4 发布")):
            label = QLabel(step)
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumWidth(92)
            self._workflow_labels.append(label)
            workflow_layout.addWidget(label)
            if i < 3:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet(f"color: {TEXT_MUTED};")
                workflow_layout.addWidget(arrow)
        workflow_layout.addStretch()
        layout.addWidget(self.workflow_card)
        self.set_workflow_step(0)

        # Workbench toolbar
        toolbar_card = CardWidget(self)
        toolbar = QHBoxLayout(toolbar_card)
        toolbar.setContentsMargins(16, 12, 16, 12)
        toolbar.setSpacing(12)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"font-size: 14px; color: {TEXT_SECONDARY};")
        toolbar.addWidget(self.count_label)

        self.select_all_cb = CheckBox("全选")
        self.select_all_cb.stateChanged.connect(self._on_select_all_changed)
        toolbar.addWidget(self.select_all_cb)

        toolbar.addStretch()

        self.collect_btn = PrimaryPushButton("开始采集")
        self.collect_btn.setToolTip("打开千帆后台采集产品，每个商品采集设置中的图片数量")
        self.collect_btn.setFixedHeight(36)
        self.collect_btn.setCursor(Qt.PointingHandCursor)
        self.collect_btn.clicked.connect(self._on_collect)
        toolbar.addWidget(self.collect_btn)

        self.batch_gen_btn = PrimaryPushButton("批量生成")
        self.batch_gen_btn.setFixedHeight(36)
        self.batch_gen_btn.setCursor(Qt.PointingHandCursor)
        self.batch_gen_btn.clicked.connect(self._on_batch_generate)
        toolbar.addWidget(self.batch_gen_btn)

        refresh_btn = PushButton("刷新")
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(self._load_from_disk)
        toolbar.addWidget(refresh_btn)

        self.batch_del_btn = PushButton("删除选中")
        self.batch_del_btn.setFixedHeight(36)
        self.batch_del_btn.clicked.connect(self._on_batch_delete)
        toolbar.addWidget(self.batch_del_btn)
        layout.addWidget(toolbar_card)

        # Persistent batch status panel
        self.queue_card = CardWidget(self)
        queue_layout = QHBoxLayout(self.queue_card)
        queue_layout.setContentsMargins(16, 10, 16, 10)
        queue_layout.setSpacing(12)
        self.queue_title_label = QLabel("批量队列")
        self.queue_title_label.setStyleSheet(f"font-weight: 700; color: {TEXT_PRIMARY};")
        queue_layout.addWidget(self.queue_title_label)
        self.queue_status_label = QLabel("未开始")
        self.queue_status_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        queue_layout.addWidget(self.queue_status_label, stretch=1)
        self.queue_progress_label = QLabel("")
        self.queue_progress_label.setStyleSheet(f"color: {TEXT_MUTED};")
        queue_layout.addWidget(self.queue_progress_label)
        layout.addWidget(self.queue_card)
        self.queue_card.setVisible(False)

        # Table
        self.table = TableWidget(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setWordWrap(False)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["", "产品标题", "图片", "状态", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table)

        # Empty state
        self.empty_widget = QWidget()
        el = QVBoxLayout(self.empty_widget)
        el.setAlignment(Qt.AlignCenter)
        el.setSpacing(12)
        empty_title = self._center_label("暂无产品数据", "18px", TEXT_PRIMARY, bold=True)
        empty_desc = self._center_label("点击「开始采集」从千帆后台同步商品素材", "14px", TEXT_SECONDARY)
        self.empty_widget.setStyleSheet(
            f"background: {SURFACE_ALT}; border: 1px dashed {BORDER}; border-radius: 8px;"
        )
        el.addWidget(empty_title)
        el.addWidget(empty_desc)
        layout.addWidget(self.empty_widget)

        self.empty_widget.setVisible(True)
        self.table.setVisible(False)

        # ── Draft card section ──
        self.draft_card = CardWidget(self)
        draft_layout = QVBoxLayout(self.draft_card)
        draft_layout.setContentsMargins(16, 12, 16, 12)
        draft_layout.setSpacing(8)

        self.draft_count_label = QLabel("已生成草稿 (0)")
        self.draft_count_label.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {TEXT_PRIMARY};")
        draft_layout.addWidget(self.draft_count_label)

        self.draft_table = TableWidget(self)
        self.draft_table.setBorderVisible(True)
        self.draft_table.setBorderRadius(8)
        self.draft_table.setWordWrap(False)
        self.draft_table.setColumnCount(6)
        self.draft_table.setHorizontalHeaderLabels(["标题", "商品名称", "方向", "状态", "创建时间", "操作"])
        self.draft_table.horizontalHeader().setStretchLastSection(True)
        self.draft_table.verticalHeader().setDefaultSectionSize(48)
        self.draft_table.verticalHeader().hide()
        draft_layout.addWidget(self.draft_table)

        self.draft_empty_label = QLabel("暂无草稿，生成内容后将在此展示")
        self.draft_empty_label.setAlignment(Qt.AlignCenter)
        self.draft_empty_label.setStyleSheet(f"color: {TEXT_MUTED}; padding: 16px;")
        draft_layout.addWidget(self.draft_empty_label)

        self.draft_card.setVisible(False)
        layout.addWidget(self.draft_card)

    def _center_label(self, text, size, color=TEXT_PRIMARY, bold=False):
        label = QLabel(text)
        weight = "bold" if bold else "normal"
        label.setStyleSheet(f"font-size: {size}; color: {color}; font-weight: {weight};")
        label.setAlignment(Qt.AlignCenter)
        return label

    def set_workflow_step(self, active_index: int):
        for i, label in enumerate(getattr(self, "_workflow_labels", [])):
            if i <= active_index:
                label.setStyleSheet(
                    f"background: {PRIMARY_LIGHT}; color: {PRIMARY}; "
                    f"border: 1px solid {PRIMARY}; border-radius: 8px; padding: 7px 10px; font-weight: 700;"
                )
            else:
                label.setStyleSheet(
                    f"background: {SURFACE_ALT}; color: {TEXT_SECONDARY}; "
                    f"border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px;"
                )

    def set_batch_progress(self, current: int, total: int, product_name: str = "", done: bool = False):
        self.queue_card.setVisible(total > 0)
        if total <= 0:
            return
        if done:
            self.queue_status_label.setText("批量生成已完成")
            self.queue_progress_label.setText(f"{total}/{total}")
            self.set_workflow_step(3)
            return
        name = product_name[:38] + ("…" if len(product_name) > 38 else "")
        self.queue_status_label.setText(f"正在生成：{name}" if name else "正在生成")
        self.queue_progress_label.setText(f"{current}/{total}")
        self.set_workflow_step(2)

    def _images_per_product(self) -> int:
        try:
            if os.path.exists(CONFIG_JSON):
                with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                    config = json.load(f)
                value = int(config.get("images_per_product", IMAGES_PER_PRODUCT))
                return max(1, min(9, value))
        except Exception as e:
            logger.warning("Load images_per_product failed: %s", e)
        return IMAGES_PER_PRODUCT

    def _on_select_all_changed(self, state):
        checked = state == Qt.Checked
        for row in range(self.table.rowCount()):
            cb = self.table.cellWidget(row, 0)
            if isinstance(cb, CheckBox):
                cb.setChecked(checked)

    def load_products(self, products: list):
        self._products = products
        self.table.setRowCount(len(products))

        for row, p in enumerate(products):
            cb = CheckBox()
            self.table.setCellWidget(row, 0, cb)

            title = p.get("title", "")
            title_item = QTableWidgetItem(title[:50])
            title_item.setToolTip(title)
            title_item.setData(Qt.UserRole, p)
            self.table.setItem(row, 1, title_item)

            # Image (sync load) — 用 QImage 直接验证，不用文件大小过滤
            img_label = QLabel()
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setFixedSize(52, 52)
            img_label.setStyleSheet("border: 1px solid #e5e7eb; border-radius: 4px;")
            local_imgs = p.get("local_images", [])
            existing_imgs = [img for img in local_imgs if os.path.exists(img)]
            img_loaded = False
            if existing_imgs:
                img_path = existing_imgs[0]
                pixmap = self._load_image_to_pixmap(img_path, 48, 48)
                if pixmap:
                    img_label.setPixmap(pixmap)
                    img_loaded = True
                else:
                    logger.warning("图片加载失败（文件损坏或格式不支持）: %s", img_path)
                img_label.setToolTip(f"已采集 {len(existing_imgs)}/{self._images_per_product()} 张")
            if not img_loaded:
                # 兜底：按 item_id 在图片目录里找
                item_id = p.get("item_id", "")
                if item_id:
                    images_dir = os.path.join(COLLECTED_DIR, "images")
                    if os.path.isdir(images_dir):
                        for d in sorted(os.listdir(images_dir)):
                            dir_path = os.path.join(images_dir, d)
                            if os.path.isdir(dir_path) and d.startswith(item_id + "_"):
                                found = [os.path.join(dir_path, f) for f in sorted(os.listdir(dir_path)) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
                                if found and os.path.exists(found[0]):
                                    pixmap = self._load_image_to_pixmap(found[0], 48, 48)
                                    if pixmap:
                                        img_label.setPixmap(pixmap)
                                        img_loaded = True
                                        img_label.setToolTip(f"已采集 {len(found)} 张 (兜底)")
                                        break
            if not img_loaded:
                # 兜底2：从 main_images URL 直接加载（不需要本地文件）
                main_imgs = p.get("main_images", [])
                logger.info("图片加载调试: item_id=%s, local_images=%s, main_images=%s",
                           p.get("item_id", ""), local_imgs, main_imgs)
                for url in main_imgs[:1]:
                    logger.info("尝试从URL加载图片: %s", url)
                    pixmap = self._load_image_from_url(url, 48, 48)
                    if pixmap:
                        img_label.setPixmap(pixmap)
                        img_loaded = True
                        img_label.setToolTip(f"已采集 {len(main_imgs)} 张 (在线)")
                        logger.info("URL加载成功: %s", url)
                        break
                    else:
                        logger.warning("URL加载失败: %s", url)
            if not img_loaded:
                img_label.setText("无图")
                img_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
                img_label.setToolTip(f"已采集 0/{self._images_per_product()} 张")
            self.table.setCellWidget(row, 2, img_label)

            # Status (Chinese label)
            status = p.get("status", "pending")
            badge = StatusBadge(status)
            badge.setFixedHeight(28)
            self.table.setCellWidget(row, 3, badge)

            # Action buttons
            action_widget = QWidget()
            al = QHBoxLayout(action_widget)
            al.setContentsMargins(8, 4, 8, 4)
            al.setSpacing(8)
            gen_btn = PrimaryPushButton("AI生成")
            gen_btn.setFixedSize(72, 32)
            gen_btn.setCursor(Qt.PointingHandCursor)
            gen_btn.clicked.connect(lambda _, r=row: self._on_generate_single(r))
            al.addWidget(gen_btn)
            self.table.setCellWidget(row, 4, action_widget)

        has_data = len(products) > 0
        self.table.setVisible(has_data)
        self.empty_widget.setVisible(not has_data)
        self.count_label.setText(f"共 {len(products)} 个产品 · 每商品采集 {self._images_per_product()} 张图")
        self.select_all_cb.blockSignals(True)
        self.select_all_cb.setChecked(False)
        self.select_all_cb.blockSignals(False)

    def _on_collect(self):
        # 进程互斥检查
        if self._collect_process_started:
            InfoBar.warning("提示", "采集进程已在运行中，请等待完成", parent=self)
            return

        project_dir = Path(__file__).resolve().parents[3]
        try:
            cmd = [
                sys.executable,
                "-m",
                "src.collector.qianfan_collector",
                "--max-pages",
                "3",
                "--images-per-product",
                str(self._images_per_product()),
            ]
            self._collect_process = subprocess.Popen(cmd, cwd=str(project_dir))
            self._collect_process_started = True
            self.set_workflow_step(0)
            self._poll_timer.start(3000)  # Check every 3s
            InfoBar.success("启动成功", f"浏览器已打开千帆后台，每个商品最多采集 {self._images_per_product()} 张图", parent=self)
        except Exception as e:
            self._collect_process_started = False
            InfoBar.error("启动失败", str(e), parent=self)

    def _check_collect_done(self):
        """Poll to check if collection process finished"""
        if self._collect_process and self._collect_process.poll() is not None:
            self._poll_timer.stop()
            self._collect_process = None
            self._collect_process_started = False
            logger.info("Collection finished, loading products...")
            self.set_workflow_step(1)
            self.collect_done.emit()

    def _load_from_disk(self):
        """Load products from disk"""
        self.collect_done.emit()

    def _get_selected(self):
        indices = []
        for row in range(self.table.rowCount()):
            cb = self.table.cellWidget(row, 0)
            if isinstance(cb, CheckBox) and cb.isChecked():
                indices.append(row)
        return indices

    def _on_batch_generate(self):
        indices = self._get_selected()
        if indices:
            products = [self._products[i] for i in indices]
            first_name = products[0].get("title", "") if products else ""
            self.set_batch_progress(1, len(products), first_name)
            self.generate_requested.emit(products)
        else:
            InfoBar.warning("提示", "请先选择产品", parent=self)

    def _on_batch_delete(self):
        indices = self._get_selected()
        if not indices:
            return

        count = len(indices)
        result = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除选中的 {count} 个产品吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return

        for i in sorted(indices, reverse=True):
            self._products.pop(i)
        self.load_products(self._products)

    def _on_generate_single(self, row):
        if 0 <= row < len(self._products):
            self.set_batch_progress(1, 1, self._products[row].get("title", ""))
            self.generate_requested.emit([self._products[row]])

    def _on_view(self, row):
        if 0 <= row < len(self._products):
            self.product_selected.emit(self._products[row])

    def add_product(self, product: dict):
        self._products.append(product)
        self.load_products(self._products)

    def update_product_status(self, index: int, status: str):
        if 0 <= index < len(self._products):
            self._products[index]["status"] = status

    def load_drafts(self, notes: list):
        """Populate the draft card table from note dicts."""
        # Filter to only draft-status notes
        drafts = [n for n in notes if n.get("status") in ("draft", "pending", "draft_saved", "failed")]
        self.draft_count_label.setText(f"已生成草稿 ({len(drafts)})")

        if not drafts:
            self.draft_card.setVisible(False)
            return

        self.draft_card.setVisible(True)
        self.draft_empty_label.setVisible(False)
        self.draft_table.setRowCount(len(drafts))

        for row, note in enumerate(drafts):
            note_id = note.get("id")
            # Title (truncated)
            title_text = note.get("title", "")
            title_item = QTableWidgetItem(title_text[:40])
            title_item.setToolTip(title_text)
            self.draft_table.setItem(row, 0, title_item)

            # Product name
            product_text = note.get("product_name", "")
            product_item = QTableWidgetItem(product_text[:30])
            product_item.setToolTip(product_text)
            self.draft_table.setItem(row, 1, product_item)

            # Direction
            dir_name = note.get("direction_name", "")
            self.draft_table.setItem(row, 2, QTableWidgetItem(dir_name))

            # Status badge
            raw_status = note.get("status", "draft")
            badge = StatusBadge(raw_status)
            badge.setFixedHeight(28)
            self.draft_table.setCellWidget(row, 3, badge)

            # Created time
            created = note.get("created_at", "")
            if created and "T" in str(created):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                    created = dt.strftime("%m-%d %H:%M")
                except Exception:
                    created = str(created)[:10]
            self.draft_table.setItem(row, 4, QTableWidgetItem(str(created)))

            # Action buttons
            action_widget = QWidget()
            al = QHBoxLayout(action_widget)
            al.setContentsMargins(4, 2, 4, 2)
            al.setSpacing(6)
            edit_btn = PushButton("编辑")
            edit_btn.setFixedSize(56, 28)
            edit_btn.setCursor(Qt.PointingHandCursor)
            if note_id is not None:
                edit_btn.clicked.connect(lambda _, nid=note_id: self.draft_edit_requested.emit(nid))
            al.addWidget(edit_btn)
            self.draft_table.setCellWidget(row, 5, action_widget)
