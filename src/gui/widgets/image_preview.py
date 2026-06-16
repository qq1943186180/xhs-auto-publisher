"""
图片预览组件
"""
import os
from PyQt5.QtWidgets import QLabel, QWidget, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap

from qfluentwidgets import PrimaryPushButton

from ..styles.theme import BG_CARD, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, PRIMARY, PRIMARY_LIGHT, RADIUS_MD


class ImagePreview(QWidget):
    """图片预览组件，支持单图/多图显示"""

    image_removed = pyqtSignal(int)  # 图片索引

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images = []  # list of file paths
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
        """添加缩略图"""
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

        # 图片
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(80, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img_label.setPixmap(scaled)
        else:
            img_label.setText("无法读取")
            img_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
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

    def _remove_image(self, index: int):
        """移除图片"""
        if 0 <= index < len(self._images):
            self._images.pop(index)
            self._rebuild_thumbnails()
            self.image_removed.emit(index)

    def _rebuild_thumbnails(self):
        """重建缩略图"""
        while self.image_layout.count():
            item = self.image_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, path in enumerate(self._images):
            self._add_thumbnail(path, i)

        self._update_visibility()

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
        self._rebuild_thumbnails()

    def set_images(self, paths: list):
        """设置图片列表"""
        self._images.clear()
        self._rebuild_thumbnails()
        self.add_images(paths)

    def setFixedHeight(self, h):
        super().setFixedHeight(h)
