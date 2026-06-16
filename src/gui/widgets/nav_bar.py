"""
左侧导航栏组件 - FluentWindow 内置导航
保留 NavBar 类以兼容外部引用，但实际导航由 FluentWindow 管理。
"""
from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QIcon

from ..styles.theme import PRIMARY


class NavBar(QWidget):
    """导航栏占位 — FluentWindow 自带导航接口"""

    NAV_ITEMS = [
        ("", "任务列表", "task_list"),
        ("", "AI 生成", "ai_generate"),
        ("", "发布管理", "publish"),
        ("", "设置", "settings"),
    ]

    page_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()  # FluentWindow 不需要独立导航栏

    def set_current_page(self, key: str):
        """兼容调用"""
        pass
