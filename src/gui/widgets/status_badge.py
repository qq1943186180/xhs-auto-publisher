"""
状态标签组件 - 使用 StateToolTip 风格的状态指示器
"""
from qfluentwidgets import StateToolTip
from PyQt5.QtWidgets import QLabel, QWidget, QHBoxLayout
from PyQt5.QtCore import Qt, QTimer

from ..styles.theme import SUCCESS, WARNING, ERROR, INFO, TEXT_SECONDARY


class StatusBadge(QWidget):
    """状态标签 — 基于 StateToolTip 样式的轻量状态指示器"""

    STYLES = {
        "pending":     (WARNING, "待处理"),
        "generating":  (INFO,    "生成中"),
        "generated":   (SUCCESS, "已生成"),
        "publishing":  (INFO,    "发布中"),
        "published":   (SUCCESS, "已发布"),
        "failed":      (ERROR,   "失败"),
        "draft":       (TEXT_SECONDARY, "草稿"),
        "draft_saved": (INFO,    "已存草稿"),
        # 步骤级状态
        "direction_generating": (INFO, "方向生成中"),
        "content_generating":   (INFO, "文案生成中"),
        "image_uploading":      (INFO, "图片上传中"),
        "image_generating":     (INFO, "生图等待中"),
        "preparing_files":      (INFO, "准备文件"),
        "filling_form":         (INFO, "填写表单"),
        "submitting":           (INFO, "提交中"),
    }

    def __init__(self, status: str = "pending", parent=None):
        super().__init__(parent)
        self._status = status
        self._setup_ui()
        self.set_status(status)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setFixedHeight(26)
        layout.addWidget(self._label)

    def set_status(self, status: str):
        self._status = status
        color, text = self.STYLES.get(status, (TEXT_SECONDARY, status))
        self._label.setText(text)
        self._label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background-color: {color}1a;
                border: 1px solid {color}33;
                border-radius: 12px;
                padding: 3px 10px;
                font-size: 12px;
                font-weight: 600;
            }}
        """)

    @property
    def status(self):
        return self._status
