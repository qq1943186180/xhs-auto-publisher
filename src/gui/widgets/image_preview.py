"""
图片预览组件
"""
import os
from PyQt5.QtWidgets import QLabel, QWidget, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap

from qfluentwidgets import PrimaryPushButton

from ..styles.theme import BG_CARD, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, PRIMARY, PRIMARY_LIGHT, RADIUS_MD
from ..workers.image_loader import AsyncImageLoader, _create_placeholder_pixmap


class ImagePreview(QWidget):
    """图片预览组件，支持单图/多图显示"""

    image_removed = pyqtSignal(int)  # 图片索引

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images = []  # list of file paths
        self._image_loader = AsyncImageLoader(self)
        self._image_loader.image_loaded.connect(self._on_async_image_loaded)
        self._thumbnail_widgets = []  # 跟踪缩略图 widget，用于精确删除
        self._setup_ui()

    def _setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)

        # 图片容器
        self.image_container = QWidget()
        self.image_layout = QHBoxLayout(self.image_container)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_layout.setSpacing(8)
        self.image_container.setLayout(self.image_layout)
        self.layout.addWidget(self.image_container)

        # 占位标签
        self.placeholder = QLabel("拖放图片到此处或点击选择")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setFixedHeight(120)
        self.placeholder.setStyleSheet(f"""
            QLabel {{
                background-color: {BG_CARD};
                border: 2px dashed {BORDER};
                border-radius: {RADIUS_MD};
                color: {TEXT_SECONDARY};
                font-size: 14px;
            }}
            QLabel:hover {{
                border-color: {PRIMARY};
                color: {PRIMARY};
            }}
        """)
        self.placeholder.setCursor(Qt.PointingHandCursor)
        self.placeholder.mousePressEvent = self._on_placeholder_click
        self.layout.addWidget(self.placeholder)

        self.setLayout(self.layout)
        self._update_visibility()

    def _on_placeholder_click(self, event):
        """占位标签点击事件"""
        from PyQt5.QtWidgets import QFileDialog
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if files:
            self.add_images(files)

    def add_images(self, paths: list):
        """添加图片"""
        for path in paths:
            if os.path.exists(path) and path not in self._images:
                self._images.append(path)
                self._add_thumbnail(path, len(self._images) - 1)
        self._update_visibility()

    def _add_thumbnail(self, path: str, index: int):
        """添加缩略图（使用异步加载）"""
        frame = QWidget()
        frame.setFixedSize(100, 100)
        frame.setStyleSheet(f"""
            QWidget {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_MD};
            }}
            QWidget:hover {{
                border-color: {PRIMARY};
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # 图片（使用异步加载器）
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignCenter)
        placeholder = _create_placeholder_pixmap(80, 70, "加载中...")
        img_label.setPixmap(placeholder)
        self._image_loader.load_single(index, path, 80, 70)
        layout.addWidget(img_label, alignment=Qt.AlignCenter)

        # 删除按钮
        del_btn = PrimaryPushButton("×")
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: {PRIMARY_LIGHT};
                color: {TEXT_PRIMARY};
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {PRIMARY};
                color: #ffffff;
            }}
        """)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda checked, i=index: self._remove_image(i))

        # 将删除按钮放在右上角
        btn_container = QWidget(frame)
        btn_container.setFixedSize(20, 20)
        btn_container.move(76, 4)
        del_btn.setParent(btn_container)
        del_btn.resize(20, 20)

        self.image_layout.addWidget(frame)
        self._thumbnail_widgets.append(frame)

    def _on_async_image_loaded(self, index: int, path: str, pixmap):
        """异步图片加载完成回调"""
        # 通过 index 找到对应的 img_label 并更新
        if 0 <= index < len(self._images):
            # 找到对应 frame 中的 img_label
            layout_items = self.image_layout.count()
            if index < layout_items:
                item = self.image_layout.itemAt(index)
                if item and item.widget():
                    frame = item.widget()
                    if frame.layout() and frame.layout().count() > 0:
                        img_item = frame.layout().itemAt(0)
                        if img_item and img_item.widget() and isinstance(img_item.widget(), QLabel):
                            img_item.widget().setPixmap(pixmap)

    def _remove_image(self, index: int):
        """移除图片 — 只移除对应 widget，不重建全部"""
        if 0 <= index < len(self._images):
            self._images.pop(index)

            # 只移除对应的 widget
            if index < self.image_layout.count():
                item = self.image_layout.takeAt(index)
                if item.widget():
                    item.widget().deleteLater()

            # 更新删除按钮的索引（因为列表已移位）
            self._rebind_delete_buttons()
            self.image_removed.emit(index)
        self._update_visibility()

    def _rebind_delete_buttons(self):
        """重新绑定删除按钮的索引"""
        for i in range(self.image_layout.count()):
            item = self.image_layout.itemAt(i)
            if item and item.widget():
                frame = item.widget()
                # 找到 del_btn
                for child in frame.findChildren(PrimaryPushButton):
                    if child.text() == "×":
                        try:
                            child.clicked.disconnect()
                        except (TypeError, RuntimeError):
                            logger.debug("Caught Exception, continuing")
                        child.clicked.connect(lambda checked, idx=i: self._remove_image(idx))
                        break

    def _update_visibility(self):
        """更新可见性"""
        has_images = len(self._images) > 0
        self.image_container.setVisible(has_images)
        self.placeholder.setVisible(not has_images)

    def get_images(self) -> list:
        """获取所有图片路径"""
        return self._images.copy()

    def clear(self):
        """清空所有图片"""
        self._images.clear()
        # 清空所有 widget
        while self.image_layout.count():
            item = self.image_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._thumbnail_widgets.clear()
        self._update_visibility()

    def set_images(self, paths: list):
        """设置图片列表"""
        self.clear()
        self.add_images(paths)

    def setFixedHeight(self, h):
        super().setFixedHeight(h)

import logging
logger = logging.getLogger(__name__)
