"""
搜索工具集成页面
搜索相关资料，用于生成更优质的文案
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QTabWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, InfoBar,
    LineEdit,
)
from src.gui.styles.theme import (
    BORDER, SURFACE_ALT,
    TEXT_PRIMARY, TEXT_SECONDARY,
    page_subtitle_style, page_title_style,
)
from src.gui.utils import PAGE_MARGINS
from src.utils.logger import get_logger

logger = get_logger("gui.search_page")


class SearchPage(QWidget):
    """搜索工具集成页面"""
    search_completed = pyqtSignal(dict)
    generate_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_results = []
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGINS)
        layout.setSpacing(16)

        # Header
        header = QVBoxLayout()
        header.setSpacing(4)

        title = QLabel("搜索资料")
        title.setStyleSheet(page_title_style())
        header.addWidget(title)

        subtitle = QLabel(
            "搜索相关资料，用于生成更优质的文案"
            "（配置 TAVILY_API_KEY 或 SERPER_API_KEY 可获得真实搜索结果）"
        )
        subtitle.setStyleSheet(page_subtitle_style())
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)

        layout.addLayout(header)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {BORDER};
                background: {SURFACE_ALT};
                border-radius: 8px;
                padding: 12px;
            }}
        """)

        # Tab 1: 在线搜索
        online_tab = QWidget()
        online_layout = QVBoxLayout(online_tab)
        online_layout.setContentsMargins(0, 12, 0, 0)
        online_layout.setSpacing(12)

        keyword_label = QLabel("搜索关键词：")
        keyword_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        online_layout.addWidget(keyword_label)

        self.keyword_edit = LineEdit()
        self.keyword_edit.setPlaceholderText("输入关键词，如：2024年配饰流行趋势")
        self.keyword_edit.setFixedHeight(36)
        self.keyword_edit.returnPressed.connect(self._on_search)
        online_layout.addWidget(self.keyword_edit)

        api_hint = QLabel(
            "💡 配置 <b>TAVILY_API_KEY</b>（tavily.com，免费 1000 次/月）"
            " 或 <b>SERPER_API_KEY</b>（serper.dev，免费 2500 次/月）可获得真实搜索结果"
        )
        api_hint.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        api_hint.setWordWrap(True)
        online_layout.addWidget(api_hint)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.search_btn = PrimaryPushButton("🔍 搜索")
        self.search_btn.setFixedSize(100, 36)
        self.search_btn.clicked.connect(self._on_search)
        btn_layout.addWidget(self.search_btn)

        self.generate_btn = PushButton("✍️ 使用资料生成")
        self.generate_btn.setFixedSize(140, 36)
        self.generate_btn.setEnabled(False)
        self.generate_btn.clicked.connect(self._on_generate)
        btn_layout.addWidget(self.generate_btn)

        online_layout.addLayout(btn_layout)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        online_layout.addWidget(self.status_label)

        online_layout.addStretch()
        self.tabs.addTab(online_tab, "🌐 在线搜索")

        # Tab 2: 手动输入
        manual_tab = QWidget()
        manual_layout = QVBoxLayout(manual_tab)
        manual_layout.setContentsMargins(0, 12, 0, 0)
        manual_layout.setSpacing(12)

        manual_label = QLabel("手动输入参考资料（在线搜索不可用时）：")
        manual_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        manual_layout.addWidget(manual_label)

        self.manual_edit = QPlainTextEdit()
        self.manual_edit.setPlaceholderText(
            "请粘贴或输入参考资料...\n\n例如：\n- 小红书配饰推荐：...\n- 2024年流行趋势：..."
        )
        self.manual_edit.setFixedHeight(200)
        manual_layout.addWidget(self.manual_edit)

        manual_gen_btn = PrimaryPushButton("✍️ 使用手动输入的资料生成")
        manual_gen_btn.setFixedHeight(36)
        manual_gen_btn.clicked.connect(self._on_manual_generate)
        manual_layout.addWidget(manual_gen_btn, 0, Qt.AlignRight)

        manual_layout.addStretch()
        self.tabs.addTab(manual_tab, "📝 手动输入")

        layout.addWidget(self.tabs)

        # Results area
        result_card = CardWidget(self)
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(16, 12, 16, 12)
        result_layout.setSpacing(12)

        result_label = QLabel("搜索结果 / 参考资料：")
        result_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        result_layout.addWidget(result_label)

        self.result_edit = QPlainTextEdit()
        self.result_edit.setPlaceholderText("搜索结果或参考资料将显示在这里...")
        self.result_edit.setFixedHeight(300)
        result_layout.addWidget(self.result_edit)

        layout.addWidget(result_card)

    def _on_search(self):
        """执行搜索（异步，不阻塞 UI）"""
        keyword = self.keyword_edit.text().strip()
        if not keyword:
            InfoBar.warning("提示", "请输入搜索关键词", parent=self)
            return

        self.search_btn.setText("搜索中...")
        self.search_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.status_label.setText("正在搜索，请稍候...")
        self.result_edit.setPlainText("正在搜索中，请稍候...")

        from src.ai.search_integration import SearchWorker
        self._worker = SearchWorker(keyword, callback=self._on_search_done)
        self._worker.start()

    def _on_search_done(self, results, error=None):
        """搜索完成回调（由 QTimer 保证在主线程执行）"""
        self.search_btn.setText("🔍 搜索")
        self.search_btn.setEnabled(True)

        if results:
            self._search_results = results
            from src.ai.search_integration import format_search_results_for_prompt
            formatted = format_search_results_for_prompt(results)
            self.result_edit.setPlainText(formatted)
            self.generate_btn.setEnabled(True)
            self.status_label.setText(f"✅ 找到 {len(results)} 条相关资料")
            InfoBar.success("搜索成功", f"找到 {len(results)} 条相关资料", parent=self)
        else:
            hint_lines = [
                "未找到相关结果。",
                "",
                "💡 提升搜索质量的方法：",
                "  1. 配置 Tavily API Key（AI 搜索，免费 1000 次/月）：",
                "     设置环境变量 TAVILY_API_KEY=你的key",
                "     免费申请：https://tavily.com",
                "  2. 配置 Serper API Key（谷歌结果，免费 2500 次/月）：",
                "     设置环境变量 SERPER_API_KEY=你的key",
                "     免费申请：https://serper.dev",
                "  3. 配置代理后 Jina 搜索可用（设置 xhs.proxy）",
                "  4. 也可切换到「手动输入」标签页粘贴参考资料",
            ]
            if error:
                hint_lines.insert(0, f"搜索出错：{error}")
                hint_lines.insert(1, "")
            self.result_edit.setPlainText("\n".join(hint_lines))
            self.generate_btn.setEnabled(False)
            self.status_label.setText("⚠️ 未找到结果，请查看提示")
            InfoBar.warning("未找到结果", "请参考结果区域的配置提示", parent=self)

    def _on_generate(self):
        """使用搜索结果生成内容"""
        if not self._search_results:
            InfoBar.warning("提示", "请先搜索获取资料", parent=self)
            return

        keyword = self.keyword_edit.text().strip()
        self.generate_requested.emit({
            "product": {
                "title": keyword,
                "description": self.result_edit.toPlainText(),
                "price": "",
                "local_images": [],
            },
            "style": "种草",
            "search_results": self.result_edit.toPlainText(),
        })
        InfoBar.info("开始生成", f"正在根据「{keyword[:20]}」生成内容...", parent=self)

    def _on_manual_generate(self):
        """使用手动输入的参考资料生成"""
        manual_text = self.manual_edit.toPlainText().strip()
        if not manual_text:
            InfoBar.warning("提示", "请先输入参考资料", parent=self)
            return

        lines = manual_text.split("\n")
        keyword = lines[0][:30] if lines else "参考资料"
        self.result_edit.setPlainText(manual_text)
        self.generate_requested.emit({
            "product": {
                "title": keyword,
                "description": manual_text,
                "price": "",
                "local_images": [],
            },
            "style": "种草",
            "search_results": manual_text,
        })
        InfoBar.info("开始生成", "正在根据手动输入的资料生成内容...", parent=self)
