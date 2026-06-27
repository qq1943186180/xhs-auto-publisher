"""
Log Console Widget - PyQt-Fluent-Widgets
支持过滤（只看错误）和复制诊断信息。
"""
import html
import logging
import platform
import sys
from datetime import datetime
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel, QApplication
from PyQt5.QtCore import Qt, pyqtSignal

from qfluentwidgets import PlainTextEdit, PushButton
from src.gui.styles.theme import ERROR, INFO, SUCCESS, TEXT_MUTED, TEXT_PRIMARY, WARNING


class LogHandler(logging.Handler):
    """Custom log handler that outputs to LogConsole"""

    def __init__(self, console):
        super().__init__()
        self.console = console

    def emit(self, record):
        msg = self.format(record)
        level = record.levelno
        self.console.append_log(msg, level)


class LogConsole(QWidget):
    """Log console widget with filter and diagnostic copy"""

    append_requested = pyqtSignal(str, int)

    LEVEL_COLORS = {
        logging.DEBUG: TEXT_MUTED,
        logging.INFO: INFO,
        logging.WARNING: WARNING,
        logging.ERROR: ERROR,
        logging.CRITICAL: ERROR,
    }

    LEVEL_LABELS = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARN",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRIT",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_count = 0
        self._max_lines = 5000
        self._all_logs: list[tuple[str, int, str]] = []  # (message, level, timestamp)
        self._filter_errors = False
        self.append_requested.connect(self._append_log, Qt.QueuedConnection)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("运行日志")
        title.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {TEXT_MUTED};")
        header.addWidget(title)
        header.addStretch()

        self.error_filter_btn = PushButton("只看错误")
        self.error_filter_btn.setFixedHeight(28)
        self.error_filter_btn.setCheckable(True)
        self.error_filter_btn.clicked.connect(self._on_toggle_error_filter)
        header.addWidget(self.error_filter_btn)

        copy_btn = PushButton("复制诊断信息")
        copy_btn.setFixedHeight(28)
        copy_btn.clicked.connect(self._on_copy_diagnostics)
        header.addWidget(copy_btn)

        clear_btn = PushButton("清空")
        clear_btn.setFixedHeight(28)
        clear_btn.clicked.connect(self.clear)
        header.addWidget(clear_btn)

        layout.addLayout(header)

        self.text_edit = PlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumBlockCount(self._max_lines)
        layout.addWidget(self.text_edit)

    def append_log(self, message: str, level: int = logging.INFO):
        self.append_requested.emit(message, level)

    def _append_log(self, message: str, level: int = logging.INFO):
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 存入缓冲区（始终保存，不受过滤影响）
        self._all_logs.append((message, level, timestamp))
        if len(self._all_logs) > self._max_lines:
            self._all_logs = self._all_logs[-self._max_lines:]

        # 如果开启了错误过滤，跳过非错误日志的显示
        if self._filter_errors and level < logging.ERROR:
            return

        self._render_log_line(message, level, timestamp)

    def _render_log_line(self, message: str, level: int, timestamp: str):
        color = self.LEVEL_COLORS.get(level, TEXT_PRIMARY)
        label = self.LEVEL_LABELS.get(level, "LOG")
        safe_message = html.escape(message)

        html_line = (
            f'<span style="color:{TEXT_MUTED};">{timestamp}</span> '
            f'<span style="color:{color};font-weight:600;">[{label}]</span> '
            f'<span style="color:{TEXT_PRIMARY};">{safe_message}</span>'
        )
        self.text_edit.appendHtml(html_line)
        self._line_count += 1

        scrollbar = self.text_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_toggle_error_filter(self):
        self._filter_errors = self.error_filter_btn.isChecked()
        self._apply_filter()

    def _apply_filter(self):
        """根据当前过滤模式重绘日志"""
        self.text_edit.clear()
        self._line_count = 0

        for message, level, timestamp in self._all_logs:
            if self._filter_errors and level < logging.ERROR:
                continue
            self._render_log_line(message, level, timestamp)

    def _on_copy_diagnostics(self):
        """复制诊断信息到剪贴板：最近 200 行日志 + 系统信息"""
        lines = []
        lines.append("=== 诊断信息 ===")
        lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"系统: {platform.platform()}")
        lines.append(f"Python: {sys.version}")
        lines.append(f"日志条数: {len(self._all_logs)}")
        lines.append("")
        lines.append("=== 最近日志 ===")

        recent = self._all_logs[-200:]
        for message, level, timestamp in recent:
            label = self.LEVEL_LABELS.get(level, "LOG")
            lines.append(f"[{timestamp}] [{label}] {message}")

        text = "\n".join(lines)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    def clear(self):
        self.text_edit.clear()
        self._line_count = 0
        self._all_logs.clear()

    def get_handler(self, level=logging.DEBUG) -> LogHandler:
        handler = LogHandler(self)
        handler.setLevel(level)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        return handler
