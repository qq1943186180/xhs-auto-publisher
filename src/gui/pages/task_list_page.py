"""
Task List Page - with auto-load after collection
"""
import json
import os
import subprocess
import sys
import logging
from pathlib import Path
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel, QTableWidgetItem, QFrame
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, TableWidget,
    CheckBox, InfoBar
)
from src.gui.styles.theme import (
    BORDER,
    INFO,
    SUCCESS,
    SURFACE_ALT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    page_subtitle_style,
    page_title_style,
)

logger = logging.getLogger(__name__)

COLLECTED_DIR = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "collected")
PRODUCTS_JSON = os.path.join(COLLECTED_DIR, "products_simple.json")
CONFIG_JSON = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "config.json")
IMAGES_PER_PRODUCT = 5


class TaskListPage(QWidget):
    """Task list page"""

    generate_requested = pyqtSignal(list)
    product_selected = pyqtSignal(dict)
    collect_done = pyqtSignal()

    def __init__(self, parent=None):
        self._products = []
        self._collect_process = None
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._check_collect_done)
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
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

    def _center_label(self, text, size, color=TEXT_PRIMARY, bold=False):
        label = QLabel(text)
        weight = "bold" if bold else "normal"
        label.setStyleSheet(f"font-size: {size}; color: {color}; font-weight: {weight};")
        label.setAlignment(Qt.AlignCenter)
        return label

    def _images_per_product(self) -> int:
        try:
            if os.path.exists(CONFIG_JSON):
                with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                    config = json.load(f)
                value = int(config.get("images_per_product", IMAGES_PER_PRODUCT))
                return max(1, min(9, value))
        except Exception as e:
            logger.warning(f"Load images_per_product failed: {e}")
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

            # Image
            img_label = QLabel()
            img_label.setAlignment(Qt.AlignCenter)
            local_imgs = p.get("local_images", [])
            existing_imgs = [img for img in local_imgs if os.path.exists(img)]
            if existing_imgs:
                pixmap = QPixmap(existing_imgs[0])
                if not pixmap.isNull():
                    scaled = pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    img_label.setPixmap(scaled)
                    img_label.setToolTip(f"已采集 {len(existing_imgs)}/{self._images_per_product()} 张")
            else:
                img_label.setText("无图")
                img_label.setStyleSheet(f"color: {TEXT_MUTED};")
                img_label.setToolTip(f"已采集 0/{self._images_per_product()} 张")
            self.table.setCellWidget(row, 2, img_label)

            # Status
            status = p.get("status", "pending")
            status_label = QLabel(status)
            status_label.setAlignment(Qt.AlignCenter)
            colors = {"pending": WARNING, "done": SUCCESS, "generating": INFO}
            status_label.setStyleSheet(f"color: {colors.get(status, TEXT_MUTED)}; font-weight: 600;")
            self.table.setCellWidget(row, 3, status_label)

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
            self._poll_timer.start(3000)  # Check every 3s
            InfoBar.success("启动成功", f"浏览器已打开千帆后台，每个商品最多采集 {self._images_per_product()} 张图", parent=self)
        except Exception as e:
            InfoBar.error("启动失败", str(e), parent=self)

    def _check_collect_done(self):
        """Poll to check if collection process finished"""
        if self._collect_process and self._collect_process.poll() is not None:
            self._poll_timer.stop()
            self._collect_process = None
            logger.info("Collection finished, loading products...")
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
            self.generate_requested.emit(products)
        else:
            InfoBar.warning("提示", "请先选择产品", parent=self)

    def _on_batch_delete(self):
        indices = self._get_selected()
        if indices:
            for i in sorted(indices, reverse=True):
                self._products.pop(i)
            self.load_products(self._products)

    def _on_generate_single(self, row):
        if 0 <= row < len(self._products):
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
