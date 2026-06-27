"""
热点主题推荐页面
从知乎/微博/百度热榜抓取热点，点击即可生成内容
"""
import logging
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QGridLayout, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, InfoBar,
    ComboBox, LineEdit,
)
from src.gui.styles.theme import (
    BORDER, ERROR, PRIMARY, SUCCESS, SURFACE_ALT,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
    page_subtitle_style, page_title_style, placeholder_style,
)
from src.gui.utils import PAGE_MARGINS
from src.gui.workers.image_loader import AsyncImageLoader, _create_placeholder_pixmap
from src.utils.logger import get_logger

logger = get_logger("gui.hot_topics_page")


class HotTopicCard(CardWidget):
    """单个热点卡片"""
    topic_clicked = pyqtSignal(dict)

    def __init__(self, topic_data: dict, parent=None):
        super().__init__(parent)
        self.topic_data = topic_data
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # 排名
        rank = self.topic_data.get("rank", 0)
        rank_label = QLabel(f"#{rank}")
        rank_label.setFixedWidth(40)
        rank_label.setAlignment(Qt.AlignCenter)
        rank_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: 700;
            color: {PRIMARY};
        """)
        layout.addWidget(rank_label)

        # 标题和内容
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title = self.topic_data.get("title", "")
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {TEXT_PRIMARY};
        """)
        text_layout.addWidget(title_label)

        desc = self.topic_data.get("description", "")
        if desc:
            desc_label = QLabel(desc[:100] + "..." if len(desc) > 100 else desc)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
            text_layout.addWidget(desc_label)

        layout.addLayout(text_layout)
        layout.addStretch()

        # 生成按钮
        gen_btn = PrimaryPushButton("生成")
        gen_btn.setFixedSize(80, 32)
        gen_btn.clicked.connect(self._on_generate)
        layout.addWidget(gen_btn)

        self.setCursor(Qt.PointingHandCursor)

    def _on_generate(self):
        self.topic_clicked.emit(self.topic_data)


class HotTopicsPage(QWidget):
    """热点主题推荐页面"""
    topic_selected = pyqtSignal(dict)  # 选中某个热点
    generate_requested = pyqtSignal(dict)  # 请求生成内容

    def __init__(self, parent=None):
        super().__init__(parent)
        self._topics = []
        self._setup_ui()
        QTimer.singleShot(500, self._load_topics)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGINS)
        layout.setSpacing(16)

        # Header
        header = QVBoxLayout()
        header.setSpacing(4)

        title = QLabel("热点主题推荐")
        title.setStyleSheet(page_title_style())
        header.addWidget(title)

        subtitle = QLabel("从知乎/微博/百度热榜抓取实时热点，点击生成内容")
        subtitle.setStyleSheet(page_subtitle_style())
        header.addWidget(subtitle)

        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        self.source_combo = ComboBox()
        self.source_combo.addItem("全部")
        self.source_combo.addItem("知乎")
        self.source_combo.addItem("微博")
        self.source_combo.addItem("百度")
        self.source_combo.setFixedWidth(120)
        self.source_combo.currentTextChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.source_combo)

        self.search_edit = LineEdit()
        self.search_edit.setPlaceholderText("搜索热点...")
        self.search_edit.setFixedWidth(200)
        self.search_edit.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.search_edit)

        toolbar.addStretch()

        refresh_btn = PushButton("🔄 刷新")
        refresh_btn.setFixedSize(100, 32)
        refresh_btn.clicked.connect(self._load_topics)
        toolbar.addWidget(refresh_btn)

        layout.addLayout(toolbar)

        # 状态标签
        self.status_label = QLabel("加载中...")
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self.status_label)

        # Topics area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
        """)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setSpacing(12)
        self.container_layout.setContentsMargins(0, 0, 12, 0)
        self.container_layout.addStretch()

        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)

    def _load_topics(self):
        """加载热点（后台线程，不卡UI）"""
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.setText("加载中...")

        def _worker():
            from src.ai.hot_topics import fetch_hot_topics
            try:
                topics = fetch_hot_topics()
            except Exception as e:
                logger.error("fetch_hot_topics failed: %s", e)
                topics = []
            # 回到主线程更新UI
            QTimer.singleShot(0, lambda: self._on_topics_loaded(topics))

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _on_topics_loaded(self, topics: list):
        """热点加载完成（主线程）"""
        self._topics = topics or []
        self._render_topics()
        if self.status_label:
            if topics:
                self.status_label.setText(f"共 {len(topics)} 个热点")
            else:
                self.status_label.setText("未获取到热点，请点击刷新")
        if topics:
            InfoBar.success("加载完成", f"共 {len(topics)} 个热点", parent=self)
        else:
            InfoBar.warning("提示", "未获取到热点，请检查网络后点击刷新", parent=self)

    def _render_topics(self):
        """渲染热点卡片"""
        # 清除旧卡片
        while self.container_layout.count() > 1:
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 过滤
        filtered = self._filter_topics()

        if not filtered:
            placeholder = QLabel("暂无热点数据，请点击刷新")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(placeholder_style())
            self.container_layout.insertWidget(0, placeholder)
            return

        for topic in filtered:
            card = HotTopicCard(topic)
            card.topic_clicked.connect(self._on_topic_clicked)
            self.container_layout.insertWidget(self.container_layout.count() - 1, card)

    def _filter_topics(self) -> list:
        """过滤热点"""
        filtered = self._topics

        # 按来源过滤
        source = self.source_combo.currentText()
        if source != "全部":
            filtered = [t for t in filtered if t.get("source") == source]

        # 按关键词搜索
        keyword = self.search_edit.text().strip()
        if keyword:
            filtered = [t for t in filtered if keyword in t.get("title", "")]

        return filtered

    def _on_filter_changed(self):
        self._render_topics()

    def _on_topic_clicked(self, topic: dict):
        """点击热点卡片 → 直接触发生成"""
        fake_product = {
            "title": topic.get("title", ""),
            "description": topic.get("description", ""),
            "price": "",
            "local_images": [],
        }
        self.generate_requested.emit({
            "product": fake_product,
            "style": "种草",
        })
