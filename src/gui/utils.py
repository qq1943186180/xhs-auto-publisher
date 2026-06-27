"""
XHS Auto Publisher GUI 工具模块
共享常量、工具函数
"""
from PyQt5.QtCore import QMargins, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap


# 统一页面边距
PAGE_MARGINS = QMargins(24, 24, 24, 36)


def status_label(status: str) -> str:
    """将内部状态码映射为中文显示文本"""
    mapping = {
        "pending": "待处理",
        "done": "已完成",
        "generating": "生成中",
        "generated": "已生成",
        "publishing": "发布中",
        "published": "已发布",
        "failed": "失败",
        "draft": "草稿",
        "draft_saved": "已存草稿",
        "待发布": "待发布",
        "草稿": "草稿",
        "已发布": "已发布",
        "已存草稿": "已存草稿",
        "发布失败": "发布失败",
    }
    return mapping.get(status, status)
