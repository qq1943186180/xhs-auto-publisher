"""
热点主题推荐弹窗
从知乎/微博/百度热榜免费抓取热点，无需 API Key
"""
import re
import logging
import threading
import urllib.request
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, pyqtSlot

from qfluentwidgets import ComboBox, PushButton, LineEdit, CardWidget
from src.gui.styles.theme import PRIMARY, TEXT_SECONDARY


logger = logging.getLogger("hot_topic")


class HotTopicDialog(QDialog):
    """热点主题推荐弹窗"""
    topic_selected = pyqtSignal(str)  # 用户选中某个热点主题

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("今日热点主题推荐")
        self.setMinimumSize(720, 540)
        self._all_cards = []   # [(topic, card_widget), ...]
        self._fetched_topics = []
        self._fetched_source = ""
        self._setup_ui()
        QTimer.singleShot(300, self._fetch_hot_topics)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # 标题
        title = QLabel("🔥 今日热点主题推荐")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        # 来源选择 + 刷新 + 过滤
        top_row = QHBoxLayout()

        top_row.addWidget(QLabel("来源:"))

        self.source_combo = ComboBox()
        self.source_combo.addItem("知乎热榜", userData="zhihu")
        self.source_combo.addItem("微博热搜", userData="weibo")
        self.source_combo.addItem("百度热搜", userData="baidu")
        self.source_combo.setFixedWidth(160)
        self.source_combo.currentIndexChanged.connect(lambda _: self._fetch_hot_topics())
        top_row.addWidget(self.source_combo)

        refresh_btn = PushButton("刷新")
        refresh_btn.setFixedHeight(32)
        refresh_btn.clicked.connect(self._fetch_hot_topics)
        top_row.addWidget(refresh_btn)

        top_row.addStretch()

        top_row.addWidget(QLabel("过滤:"))
        self.filter_edit = LineEdit()
        self.filter_edit.setPlaceholderText("输入关键词过滤...")
        self.filter_edit.textChanged.connect(self._filter_topics)
        self.filter_edit.setFixedHeight(32)
        self.filter_edit.setFixedWidth(240)
        top_row.addWidget(self.filter_edit)

        layout.addLayout(top_row)

        # 状态标签
        self.status_label = QLabel("正在获取热点...")
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        layout.addWidget(self.status_label)

        # 滚动区域：热点卡片
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.card_widget = QWidget()
        self.card_layout = QVBoxLayout(self.card_widget)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(8)
        self.card_layout.addStretch()
        self.scroll.setWidget(self.card_widget)
        layout.addWidget(self.scroll, 1)

        # 底部：自定义主题输入
        layout.addWidget(QLabel("或输入自定义主题："))
        self.custom_edit = LineEdit()
        self.custom_edit.setPlaceholderText("输入你想要写的主题，回车确认")
        self.custom_edit.setFixedHeight(36)
        self.custom_edit.returnPressed.connect(self._on_custom_topic)
        layout.addWidget(self.custom_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = PushButton("关闭")
        close_btn.setFixedHeight(36)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ============================================================
    # 抓取热点（后台线程）
    # ============================================================

    def _fetch_hot_topics(self):
        """后台线程抓取热点"""
        self.status_label.setText("正在获取热点...")
        self.source_combo.setEnabled(False)

        def _worker():
            source = self.source_combo.currentData()
            topics = []
            try:
                if source == "zhihu":
                    topics = self._fetch_zhihu()
                elif source == "weibo":
                    topics = self._fetch_weibo()
                elif source == "baidu":
                    topics = self._fetch_baidu()
            except Exception as e:
                logger.warning("Fetch hot topics failed: %s", e)

            # 存到成员变量，用 timer 回到主线程更新 UI
            self._fetched_topics = topics
            self._fetched_source = source
            QTimer.singleShot(0, self._update_cards)

        threading.Thread(target=_worker, daemon=True).start()

    def _fetch_zhihu(self) -> list:
        """用 Jina 免费 API 抓知乎热榜"""
        html = self._urlopen("https://r.jina.ai/https://www.zhihu.com/hot")
        if not html:
            return self._default_topics()
        # Jina 返回 markdown，提取标题行
        lines = [l.strip() for l in html.splitlines() if l.strip()]
        topics = []
        for line in lines:
            m = re.search(r'[\d]+\.\s*\*?([\u4e00-\u9fff].{4,60})\*?', line)
            if m:
                title = m.group(1).strip().strip('*')
                if title and len(title) > 4:
                    topics.append(title)
            if len(topics) >= 20:
                break
        if not topics:
            for line in lines:
                clean = line.strip().lstrip('*#').strip()
                if re.match(r'[\u4e00-\u9fff]', clean) and 5 < len(clean) < 80:
                    topics.append(clean)
                    if len(topics) >= 20:
                        break
        return topics[:20] if topics else self._default_topics()

    def _fetch_weibo(self) -> list:
        """抓微博热搜"""
        html = self._urlopen("https://r.jina.ai/https://s.weibo.com/top/summary")
        if not html:
            return self._default_topics()
        lines = [l.strip() for l in html.splitlines() if l.strip()]
        topics = []
        skip_words = {"搜索", "登录", "微博", "热搜", "更多"}
        for line in lines:
            clean = line.strip().lstrip('*#').strip()
            if re.match(r'[\u4e00-\u9fff]', clean) and 5 < len(clean) < 80:
                if not any(sw in clean for sw in skip_words):
                    topics.append(clean)
                    if len(topics) >= 20:
                        break
        return topics[:20] if topics else self._default_topics()

    def _fetch_baidu(self) -> list:
        """抓百度热搜"""
        html = self._urlopen("https://r.jina.ai/https://top.baidu.com/board?tab=realtime")
        if not html:
            return self._default_topics()
        lines = [l.strip() for l in html.splitlines() if l.strip()]
        topics = []
        for line in lines:
            clean = line.strip().lstrip('*#').strip()
            if re.match(r'[\u4e00-\u9fff]', clean) and 5 < len(clean) < 80:
                topics.append(clean)
                if len(topics) >= 20:
                    break
        return topics[:20] if topics else self._default_topics()

    def _urlopen(self, url: str) -> str:
        """带超时的 URL 读取"""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            logger.warning("urlopen failed for %s: %s", url, e)
            return ""

    def _default_topics(self) -> list:
        return [
            "AI 大模型最新进展", "小红书运营技巧分享", "2026 年副业推荐",
            "日常穿搭灵感分享", "家居好物推荐", "美妆新品测评",
            "职场效率工具推荐", "旅行攻略分享", "美食制作教程",
            "健身打卡分享", "读书笔记分享", "宠物养护经验",
        ]

    # ============================================================
    # 主线程 UI 更新
    # ============================================================

    @pyqtSlot()
    def _update_cards(self):
        """主线程更新热点卡片"""
        self.source_combo.setEnabled(True)
        topics = self._fetched_topics
        source = self._fetched_source

        # 清空旧卡片
        while self.card_layout.count() > 1:
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._all_cards = []

        if not topics:
            self.status_label.setText("获取失败，请检查网络后点「刷新」")
            return

        self.status_label.setText(f"找到 {len(topics)} 个热点主题（来源：{source}）")

        for i, topic in enumerate(topics):
            card = CardWidget()
            card.setFixedHeight(48)
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 6, 14, 6)
            idx_label = QLabel(f"{i+1}")
            idx_label.setFixedWidth(32)
            idx_label.setStyleSheet(f"color: {PRIMARY}; font-weight: 700; font-size: 14px;")
            cl.addWidget(idx_label)
            topic_label = QLabel(topic)
            topic_label.setWordWrap(True)
            topic_label.setStyleSheet("font-size: 13px;")
            cl.addWidget(topic_label, 1)

            # 点击卡片选中主题
            card._topic_text = topic
            card.mousePressEvent = self._make_card_click_handler(topic)
            card.setCursor(Qt.PointingHandCursor)

            self.card_layout.insertWidget(self.card_layout.count() - 1, card)
            self._all_cards.append((topic, card))

    def _make_card_click_handler(self, topic: str):
        """为每个卡片生成独立的 click 回调"""
        def _handler(_event):
            self._on_topic_clicked(topic)
        return _handler

    def _filter_topics(self, text: str):
        """根据过滤框文字显示/隐藏卡片"""
        text = (text or "").lower()
        for topic, card in self._all_cards:
            card.setVisible(text in topic.lower())

    def _on_topic_clicked(self, topic: str):
        self.topic_selected.emit(topic)
        self.accept()

    def _on_custom_topic(self):
        text = self.custom_edit.text().strip()
        if text:
            self.topic_selected.emit(text)
            self.accept()
