"""
URL 内容提取页面
粘贴网页链接，自动提炼主题并生成内容
提取失败时支持手动输入主题
"""
import logging
import threading
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QInputDialog,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, InfoBar,
    LineEdit,
)
from src.gui.styles.theme import (
    BORDER, ERROR, PRIMARY, SUCCESS, SURFACE_ALT,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
    page_subtitle_style, page_title_style, placeholder_style,
)
from src.gui.utils import PAGE_MARGINS
from src.utils.logger import get_logger

logger = get_logger("gui.url_extract_page")


class URLExtractPage(QWidget):
    """URL 内容提取页面"""
    extract_completed = pyqtSignal(dict)
    generate_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._extracted_topic = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGINS)
        layout.setSpacing(16)

        # Header
        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("URL 内容提取")
        title.setStyleSheet(page_title_style())
        header.addWidget(title)
        subtitle = QLabel("粘贴网页链接，自动提炼主题并生成小红书内容")
        subtitle.setStyleSheet(page_subtitle_style())
        header.addWidget(subtitle)
        layout.addLayout(header)

        # 输入区
        input_card = CardWidget(self)
        input_layout = QVBoxLayout(input_card)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(12)

        url_label = QLabel("网页链接：")
        url_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        input_layout.addWidget(url_label)

        self.url_edit = LineEdit()
        self.url_edit.setPlaceholderText("https://...")
        self.url_edit.setFixedHeight(36)
        self.url_edit.returnPressed.connect(self._on_extract)
        input_layout.addWidget(self.url_edit)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.extract_btn = PrimaryPushButton("🔍 提取主题")
        self.extract_btn.setFixedSize(120, 36)
        self.extract_btn.clicked.connect(self._on_extract)
        btn_layout.addWidget(self.extract_btn)

        self.manual_btn = PushButton("✏️ 手动输入主题")
        self.manual_btn.setFixedSize(140, 36)
        self.manual_btn.setToolTip("如果自动提取失败，可以手动输入主题")
        self.manual_btn.clicked.connect(self._on_manual_topic)
        btn_layout.addWidget(self.manual_btn)

        self.generate_btn = PushButton("✍️ 生成内容")
        self.generate_btn.setFixedSize(120, 36)
        self.generate_btn.setEnabled(False)
        self.generate_btn.clicked.connect(self._on_generate)
        btn_layout.addWidget(self.generate_btn)

        input_layout.addLayout(btn_layout)
        layout.addWidget(input_card)

        # 结果区
        result_card = CardWidget(self)
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(16, 12, 16, 12)
        result_layout.setSpacing(12)

        result_label = QLabel("提取结果：")
        result_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        result_layout.addWidget(result_label)

        self.result_edit = QPlainTextEdit()
        self.result_edit.setPlaceholderText(
            "提取的主题和内容将显示在这里...\n\n"
            "如果自动提取失败，请点击「手动输入主题」按钮"
        )
        self.result_edit.setFixedHeight(200)
        result_layout.addWidget(self.result_edit)

        layout.addWidget(result_card)

        # 手动输入区
        manual_card = CardWidget(self)
        manual_layout = QVBoxLayout(manual_card)
        manual_layout.setContentsMargins(16, 12, 16, 12)
        manual_layout.setSpacing(8)

        manual_label = QLabel("直接输入主题生成：")
        manual_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        manual_layout.addWidget(manual_label)

        manual_row = QHBoxLayout()
        self.manual_edit = LineEdit()
        self.manual_edit.setPlaceholderText("直接输入主题，如：2024年配饰流行趋势")
        self.manual_edit.setFixedHeight(36)
        self.manual_edit.returnPressed.connect(self._on_manual_generate)
        manual_row.addWidget(self.manual_edit)

        manual_gen_btn = PrimaryPushButton("✍️ 用此主题生成")
        manual_gen_btn.setFixedHeight(36)
        manual_gen_btn.clicked.connect(self._on_manual_generate)
        manual_row.addWidget(manual_gen_btn)

        manual_layout.addLayout(manual_row)
        layout.addWidget(manual_card)
        layout.addStretch()

    # ============================================================
    # 自动提取
    # ============================================================

    def _on_extract(self):
        """提取 URL 内容（后台线程）"""
        url = self.url_edit.text().strip()
        if not url:
            InfoBar.warning("提示", "请输入网页链接", parent=self)
            return

        self.extract_btn.setText("提取中...")
        self.extract_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.result_edit.setPlainText("正在提取，请稍候...")

        def _worker():
            try:
                from src.ai.url_extractor import extract_url_content
                result = extract_url_content(url)
                # 用信号安全地回到主线程
                QTimer.singleShot(0, lambda: self._on_extract_done(result))
            except Exception as e:
                logger.error("URL extract failed: %s", e)
                QTimer.singleShot(0, lambda: self._on_extract_done(None, str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_extract_done(self, result, error=None):
        """提取完成（主线程）"""
        self.extract_btn.setText("🔍 提取主题")
        self.extract_btn.setEnabled(True)

        if error:
            self.result_edit.setPlainText(
                f"提取失败：{error}\n\n建议：\n1. 检查链接是否正确\n2. 点击「手动输入主题」直接输入"
            )
            InfoBar.error(
                "提取失败",
                "无法提取内容，请手动输入主题",
                parent=self,
                duration=5000,
            )
            return

        if result and result.get("topic"):
            self._extracted_topic = result.get("topic", "")
            summary = result.get("summary", "")[:300]
            self.result_edit.setPlainText(f"主题：{self._extracted_topic}\n\n内容摘要：{summary}")
            self.generate_btn.setEnabled(True)
            InfoBar.success(
                "提取成功",
                f"主题：{self._extracted_topic[:30]}",
                parent=self,
            )
        else:
            self.result_edit.setPlainText(
                "自动提取失败，该网站可能需要登录或使用了动态渲染。\n\n"
                "请点击「手动输入主题」按钮，直接输入你想要的主题。"
            )
            self.generate_btn.setEnabled(False)
            InfoBar.warning(
                "提取失败",
                "无法自动提取，请手动输入主题",
                parent=self,
                duration=5000,
            )

    # ============================================================
    # 手动输入
    # ============================================================

    def _on_manual_topic(self):
        """手动输入主题（弹窗）"""
        text, ok = QInputDialog.getText(
            self, "手动输入主题", "请输入主题："
        )
        if ok and text.strip():
            self._apply_manual_topic(text.strip())

    def _on_manual_generate(self):
        """直接从手动输入框生成"""
        text = self.manual_edit.text().strip()
        if not text:
            InfoBar.warning("提示", "请输入主题", parent=self)
            return
        self._apply_manual_topic(text)

    def _apply_manual_topic(self, topic: str):
        """应用手动输入的主题"""
        self._extracted_topic = topic
        self.result_edit.setPlainText(f"主题（手动输入）：{topic}")
        self.generate_btn.setEnabled(True)
        InfoBar.success("已设置主题", topic[:30], parent=self)

    # ============================================================
    # 生成本内容
    # ============================================================

    def _on_generate(self):
        """使用提取的主题生成内容"""
        if not self._extracted_topic:
            InfoBar.warning("提示", "请先提取或输入主题", parent=self)
            return

        fake_product = {
            "title": self._extracted_topic,
            "description": self.result_edit.toPlainText(),
            "price": "",
            "local_images": [],
        }

        self.generate_requested.emit({
            "product": fake_product,
            "style": "种草",
        })
