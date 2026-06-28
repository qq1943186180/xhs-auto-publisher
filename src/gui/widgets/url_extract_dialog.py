"""
URL 内容提取弹窗
粘贴网页链接，用 url_extractor 模块抓取内容并提炼主题
提取失败时支持手动输入主题
"""
import logging
import threading

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

from qfluentwidgets import PushButton, InfoBar
from src.gui.styles.theme import TEXT_SECONDARY


logger = logging.getLogger("url_extract")


class URLExtractDialog(QDialog):
    """URL 内容提取弹窗"""
    topic_extracted = pyqtSignal(str)  # 提炼出的主题

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("URL 内容提取")
        self.setMinimumSize(600, 320)
        self._setup_ui()
        self._url_edit.setFocus()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("🌐 粘贴网页链接，自动提炼主题")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        layout.addWidget(title)

        # URL 输入
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("链接:"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://www.xiaohongshu.com/explore/...")
        self._url_edit.setFixedHeight(36)
        self._url_edit.returnPressed.connect(self._on_extract)
        url_row.addWidget(self._url_edit, 1)
        extract_btn = PushButton("提取")
        extract_btn.setFixedHeight(36)
        extract_btn.setMinimumWidth(80)
        extract_btn.clicked.connect(self._on_extract)
        url_row.addWidget(extract_btn)
        layout.addLayout(url_row)

        # 状态
        self._status_label = QLabel("等待输入链接...")
        self._status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._status_label)

        # 提取结果展示
        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        self._result_label.setStyleSheet(
            "padding: 12px; background: #f5f5f5; border-radius: 6px; font-size: 13px;"
        )
        self._result_label.setMinimumHeight(80)
        self._result_label.hide()
        layout.addWidget(self._result_label)

        # 底部按钮
        btn_row = QHBoxLayout()
        self._use_btn = PushButton("使用此主题")
        self._use_btn.setFixedHeight(36)
        self._use_btn.setMinimumWidth(120)
        self._use_btn.setEnabled(False)
        self._use_btn.clicked.connect(self._on_use_topic)
        btn_row.addWidget(self._use_btn)
        # 备选：手动输入
        manual_btn = PushButton("手动输入主题")
        manual_btn.setFixedHeight(36)
        manual_btn.clicked.connect(self._on_manual_topic)
        btn_row.addWidget(manual_btn)
        btn_row.addStretch()
        cancel_btn = PushButton("关闭")
        cancel_btn.setFixedHeight(36)
        cancel_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._extracted_topic = ""
        self._extracted_summary = ""

    def _on_extract(self):
        url = self._url_edit.text().strip()
        if not url:
            InfoBar.warning("提示", "请先粘贴链接", parent=self)
            return
        self._status_label.setText("正在抓取内容...")
        self._use_btn.setEnabled(False)
        self._result_label.hide()

        def _worker():
            try:
                from src.ai.url_extractor import extract_url_content
                result = extract_url_content(url)
                QTimer.singleShot(0, lambda: self._on_extract_done(result, ""))
            except Exception as e:
                logger.warning("URL extract failed: %s", e)
                QTimer.singleShot(0, lambda: self._on_extract_done({}, str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_extract_done(self, result: dict, error: str):
        if error:
            self._status_label.setText(f"提取失败：{error}")
            return

        topic = result.get("topic", "") if result else ""
        summary = result.get("summary", "") if result else ""

        if topic:
            self._extracted_topic = topic
            self._extracted_summary = summary
            self._status_label.setText("提取完成！请确认主题后点击「使用此主题」")
            display = f"提炼主题：<b>{topic}</b>"
            if summary:
                short = summary[:120].replace("<", "&lt;").replace(">", "&gt;")
                display += f"<br><small style='color:#888'>{short}…</small>"
            self._result_label.setText(display)
            self._result_label.show()
            self._use_btn.setEnabled(True)
        else:
            self._status_label.setText("自动提取失败，请手动输入主题")

    def _on_use_topic(self):
        if self._extracted_topic:
            self.topic_extracted.emit(self._extracted_topic)
            self.accept()

    def _on_manual_topic(self):
        """自动提取失败时，手动输入主题"""
        from PyQt5.QtWidgets import QInputDialog
        topic, ok = QInputDialog.getText(
            self, "手动输入主题", "请输入主题：",
        )
        if ok and topic.strip():
            self._extracted_topic = topic.strip()
            self.topic_extracted.emit(self._extracted_topic)
            self.accept()
