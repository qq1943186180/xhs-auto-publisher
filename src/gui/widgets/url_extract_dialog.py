"""
URL 内容提取弹窗
粘贴网页链接，用 Jina 免费 API 抓取内容并提炼主题
"""
import logging
import threading
import urllib.request
import re

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
                content = self._fetch_url(url)
                topic = self._extract_topic(content, url)
                # 回到主线程更新 UI
                self._extracted_topic = topic
                QTimer.singleShot(0, lambda: self._on_extract_done(topic, ""))
            except Exception as e:
                logger.warning("URL extract failed: %s", e)
                QTimer.singleShot(0, lambda: self._on_extract_done("", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _fetch_url(self, url: str) -> str:
        """抓取网页内容（Jina 不可用时降级为直接请求）"""
        if not url.startswith("http"):
            url = "https://" + url

        # 方法1：尝试 Jina API
        try:
            api_url = f"https://r.jina.ai/{url}"
            req = urllib.request.Request(api_url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception:
            pass  # 降级到方法2

        # 方法2：直接请求网页，提取 <title>
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                # 只保留前 5000 字符，避免内容过大
                return content[:5000]
        except Exception as e:
            raise RuntimeError(f"无法抓取网页内容：{e}")

    def _extract_topic(self, content: str, url: str) -> str:
        """从抓取的内容中提炼主题（兼容 Jina 不可用的情况）"""
        import re

        def _clean_title(t: str) -> str:
            """清理标题：去网站后缀、多余空白"""
            t = re.sub(r"\s+", " ", t).strip()
            # 去掉常见的网站后缀
            t = re.sub(r"\s*[-|·|_]\s*MSN\s*$", "", t, flags=re.IGNORECASE)
            t = re.sub(r"\s*[-|·|_]\s*新浪.*$", "", t)
            t = re.sub(r"\s*[-|·|_]\s*知乎.*$", "", t)
            t = re.sub(r"\s*[-|·|_]\s*小红书.*$", "", t)
            t = re.sub(r"\s*[-|·|_]\s*微博.*$", "", t)
            t = re.sub(r"\s*[-|·|_]\s*百度.*$", "", t)
            return t.strip()

        # 收集所有候选标题，按优先级排序
        candidates = []

        # 优先1：<meta property="og:title">（语义最准确）
        # 匹配 property/name 在前 或 content 在前 两种属性顺序
        og_match = re.search(r'<meta[^>]+(?:property|name)\s*=\s*["\'](?:og:)?title["\'][^>]*content\s*=\s*["\'](.*?)["\']', content, re.IGNORECASE | re.DOTALL)
        if not og_match:
            og_match = re.search(r'<meta[^>]+content\s*=\s*["\'](.*?)["\'][^>]*(?:property|name)\s*=\s*["\'](?:og:)?title["\']', content, re.IGNORECASE | re.DOTALL)
        if og_match:
            t = _clean_title(og_match.group(1))
            if len(t) >= 3:
                candidates.append(t)

        # 优先2：HTML <title> 标签
        title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
        if title_match:
            t = _clean_title(title_match.group(1))
            if len(t) >= 3:
                candidates.append(t)

        # 优先3：Jina markdown 格式的 # 标题
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        for line in lines:
            if line.startswith("# "):
                t = _clean_title(line.lstrip("#").strip())
                if len(t) >= 3:
                    candidates.append(t)
                    break  # 只取第一个

        # 如果有候选标题，返回第一个
        if candidates:
            return candidates[0][:80]

        # 优先4：找第一个有意义的段落（去掉 HTML 标签后）
        text_only = re.sub(r"<[^>]+>", " ", content)
        text_only = re.sub(r"\s+", " ", text_only).strip()
        if len(text_only) > 20:
            snippet = text_only[:80].strip()
            if len(snippet) >= 5:
                return snippet

        # 优先5：从 URL 推断
        from urllib.parse import urlparse
        parsed = urlparse(url if "://" in url else "https://" + url)
        netloc = parsed.netloc.lower()
        path = parsed.path.strip("/")

        # 去掉常见域名
        for domain in ["www.", "m.", "mobile."]:
            netloc = netloc.replace(domain, "")
        site_name = netloc.replace(".com", "").replace(".cn", "").replace(".org", "").replace(".net", "")

        if path:
            path_part = path.split("/")[-1]
            path_part = re.sub(r"[-_]+", " ", path_part)
            path_part = re.sub(r"\.(html|htm|php|aspx?|jsp).*$", "", path_part, flags=re.IGNORECASE)
            if len(path_part) > 5:
                return path_part[:60]

        return f"来自 {site_name} 的内容"

    def _on_extract_done(self, topic: str, error: str):
        if error:
            self._status_label.setText(f"提取失败：{error}")
            return
        self._status_label.setText("提取完成！请确认主题后点击「使用此主题」")
        self._result_label.setText(f"提炼主题：<b>{topic}</b>")
        self._result_label.show()
        self._use_btn.setEnabled(True)
        self._extracted_topic = topic

    def _on_use_topic(self):
        if self._extracted_topic:
            self.topic_extracted.emit(self._extracted_topic)
            self.accept()

    def _on_manual_topic(self):
        """API 失败时，手动输入主题"""
        from PyQt5.QtWidgets import QInputDialog
        topic, ok = QInputDialog.getText(
            self, "手动输入主题", "Jina API 暂不可用，请手动输入主题：",
        )
        if ok and topic.strip():
            self._extracted_topic = topic.strip()
            self.topic_extracted.emit(self._extracted_topic)
            self.accept()
