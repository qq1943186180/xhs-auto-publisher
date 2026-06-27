"""
文案模板编辑弹窗
从 AI 生成页直接编辑文案模板，无需跳去设置页。
"""
import logging
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QMessageBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from qfluentwidgets import PrimaryPushButton, PushButton, StrongBodyLabel

from src.ai.prompt_templates import (
    CONTENT_TEMPLATE_1, CONTENT_TEMPLATE_2, CONTENT_TEMPLATE_3,
    CONTENT_TEMPLATE_4, CONTENT_TEMPLATE_5,
)
from src.utils.logger import get_logger

logger = get_logger("gui.template_edit_dialog")

# 模板 key → 显示名 + 默认文本
TEMPLATE_MAP = {
    "content_template_1": ("日常种草", CONTENT_TEMPLATE_1),
    "content_template_2": ("真实测评", CONTENT_TEMPLATE_2),
    "content_template_3": ("搭配灵感", CONTENT_TEMPLATE_3),
    "content_template_4": ("选购参考", CONTENT_TEMPLATE_4),
    "content_template_5": ("日常记录", CONTENT_TEMPLATE_5),
}


class TemplateEditDialog(QDialog):
    """文案模板编辑弹窗"""

    def __init__(self, template_key: str, current_text: str, parent=None):
        super().__init__(parent)
        self.template_key = template_key
        self._saved = False
        display_name = TEMPLATE_MAP.get(template_key, ("未知模板", ""))[0]
        self.setWindowTitle(f"编辑文案模板 — {display_name}")
        self.setMinimumSize(700, 560)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 标题
        title = StrongBodyLabel(f"编辑模板：{display_name}")
        layout.addWidget(title)

        hint = QLabel("修改后点「保存」，下次生成文案时会用这个版本。点「恢复默认」则清除自定义内容。")
        hint.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(hint)

        # 编辑器
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(current_text)
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.Monospace)
        self.editor.setFont(font)
        layout.addWidget(self.editor)

        # 字数统计
        self.char_label = QLabel(f"{len(current_text)} 字符")
        self.char_label.setStyleSheet("color: #999; font-size: 12px;")
        self.editor.textChanged.connect(self._update_char_count)
        layout.addWidget(self.char_label)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        reset_btn = PushButton("恢复默认")
        reset_btn.setFixedHeight(36)
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()

        cancel_btn = PushButton("取消")
        cancel_btn.setFixedHeight(36)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = PrimaryPushButton("保存")
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _update_char_count(self):
        text = self.editor.toPlainText()
        self.char_label.setText(f"{len(text)} 字符")

    def _on_reset(self):
        default_text = TEMPLATE_MAP.get(self.template_key, ("", ""))[1]
        self.editor.setPlainText(default_text)
        InfoBar.success("已恢复默认", "模板已恢复为默认内容", parent=self)

    def _on_save(self):
        text = self.editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "模板内容不能为空")
            return

        # 保存到 config.json 的 prompts 字段
        try:
            from src.config import get_config_manager
            cfg = get_config_manager()
            prompts = cfg.get("prompts", {}) or {}
            if not isinstance(prompts, dict):
                prompts = {}
            prompts[self.template_key] = text
            # 保存到 config.json
            import json
            from pathlib import Path
            config_path = Path.home() / ".xhs-publisher" / "config.json"
            full_config = {}
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    full_config = json.load(f)
            full_config["prompts"] = prompts
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(full_config, f, indent=2, ensure_ascii=False)
            logger.info("Template %s saved to config.json", self.template_key)
        except Exception as e:
            logger.warning("Save template failed: %s", e)
            QMessageBox.warning(self, "保存失败", str(e))
            return

        self._saved = True
        self.accept()

    def get_saved_text(self) -> str:
        return self.editor.toPlainText().strip() if self._saved else ""

    @staticmethod
    def get_template_text(template_key: str) -> str:
        """读取模板当前文本（config 覆盖 > 默认）"""
        import json
        from pathlib import Path
        try:
            config_path = Path.home() / ".xhs-publisher" / "config.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                prompts = config.get("prompts", {}) or {}
                if isinstance(prompts, dict) and template_key in prompts and prompts[template_key]:
                    return prompts[template_key]
        except Exception:
            pass
        # 返回默认
        return TEMPLATE_MAP.get(template_key, ("", ""))[1]
