"""
Log Console Widget - PyQt-Fluent-Widgets
"""
import logging
from datetime import datetime
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel
from PyQt5.QtCore import Qt

from qfluentwidgets import PlainTextEdit, PushButton
from src.gui.styles.theme import ERROR, INFO, TEXT_MUTED, TEXT_PRIMARY, WARNING


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
    """Log console widget"""

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
        color = self.LEVEL_COLORS.get(level, TEXT_PRIMARY)
        label = self.LEVEL_LABELS.get(level, "LOG")
        timestamp = datetime.now().strftime("%H:%M:%S")

        html = (
            f'<span style="color:{TEXT_MUTED};">{timestamp}</span> '
            f'<span style="color:{color};font-weight:600;">[{label}]</span> '
            f'<span style="color:{TEXT_PRIMARY};">{message}</span>'
        )
        self.text_edit.appendHtml(html)
        self._line_count += 1

        scrollbar = self.text_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear(self):
        self.text_edit.clear()
        self._line_count =  0

    def get_handler(self, level=logging.DEBUG) -> LogHandler:
        handler = LogHandler(self)
        handler.setLevel(level)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        return handler
