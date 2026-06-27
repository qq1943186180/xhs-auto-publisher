"""
生成前提示词预览对话框
用户点击"生成内容与图片"后，先预览即将使用的文案和图片提示词，确认后再开始生成。
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPlainTextEdit, QDialogButtonBox, QWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from qfluentwidgets import PrimaryPushButton, PushButton
from src.gui.styles.theme import TEXT_PRIMARY, TEXT_SECONDARY, BORDER, SURFACE_ALT, PRIMARY


class PromptPreviewDialog(QDialog):
    """生成前提示词预览对话框"""

    settings_requested = pyqtSignal()  # 用户点击"去设置修改"

    def __init__(self, product: dict, style: str, parent=None):
        super().__init__(parent)
        self._product = product
        self._style = style
        self.setWindowTitle("生成预览 - 确认提示词")
        self.setMinimumSize(800, 650)
        self.resize(860, 720)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        # 顶部信息行
        product_name = self._product.get("title", "") if self._product else ""
        info = QLabel(f"产品: {product_name}    风格: {self._style}")
        info.setStyleSheet(f"font-size: 14px; color: {TEXT_PRIMARY};")
        layout.addWidget(info)

        hint = QLabel("以下是本次生成将使用的提示词。如需修改请到设置页编辑，或点击“开始生成”直接继续。")
        hint.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY};")
        layout.addWidget(hint)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(10)

        # 收集所有提示词
        prompts = self._collect_prompts()

        # 文案生成提示词
        self._add_section(scroll_layout, "文案生成提示词", prompts["text"])

        # 图片生成提示词
        self._add_section(scroll_layout, "图片生成提示词", prompts["image"])

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # 底部按钮行
        btn_row = QHBoxLayout()
        settings_btn = PushButton("去设置修改")
        settings_btn.clicked.connect(self._on_settings)
        btn_row.addWidget(settings_btn)

        btn_row.addStretch()

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        start_btn = PrimaryPushButton("开始生成")
        start_btn.setFixedHeight(38)
        start_btn.setMinimumWidth(120)
        start_btn.clicked.connect(self.accept)
        btn_row.addWidget(start_btn)

        layout.addLayout(btn_row)

    def _collect_prompts(self) -> dict:
        """收集本次生成会用到的所有提示词"""
        product = self._product or {}
        product_name = product.get("title", "")
        description = product.get("description", "")
        price = product.get("price", "")
        selling_points = product.get("tags", "") or product.get("selling_points", "")

        text_prompts = []
        image_prompts = []

        try:
            from src.ai.prompt_templates import (
                get_custom_prompt,
                get_direction_prompt,
                get_direction_content_prompt,
                IMAGE_STYLE_GUIDES,
                IMAGE_CAMERA_GUIDES,
            )

            # 方向提案 system prompt
            dir_sys, _ = get_direction_prompt(
                product_name=product_name,
                description=description,
                price=price or "未知",
                selling_points=selling_points,
                style=self._style,
            )
            text_prompts.append(("方向提案 (system prompt)", dir_sys))

            # 方向扩写 system prompt
            dir_content_sys, _ = get_direction_content_prompt(
                product_name=product_name,
                description=description,
                price=price or "未知",
                selling_points=selling_points,
                direction={"name": "示例方向", "target_audience": "-", "angle": "-", "hook_type": "-", "style_hint": "-"},
                style=self._style,
            )
            text_prompts.append(("方向扩写 (system prompt)", dir_content_sys))

            # 图片风格指南（含自定义覆盖）
            style_labels = {
                "style_a": "风格 A - 博主随手拍",
                "style_b": "风格 B - 买家秀细节",
                "style_c": "风格 C - 生活随拍",
            }
            for key, label in style_labels.items():
                custom = get_custom_prompt(f"image_{key}")
                text = custom if custom else IMAGE_STYLE_GUIDES.get(key, "")
                suffix = " (自定义)" if custom else ""
                image_prompts.append((f"{label}{suffix}", text))

            # 图片相机指南（含自定义覆盖）
            camera_labels = [
                ("image_camera_a", "相机 A - iPhone"),
                ("image_camera_b", "相机 B - Samsung"),
                ("image_camera_c", "相机 C - Portrait"),
            ]
            for i, (config_key, label) in enumerate(camera_labels):
                custom = get_custom_prompt(config_key)
                text = custom if custom else (IMAGE_CAMERA_GUIDES[i] if i < len(IMAGE_CAMERA_GUIDES) else "")
                suffix = " (自定义)" if custom else ""
                image_prompts.append((f"{label}{suffix}", text))

        except Exception as e:
            text_prompts.append(("加载失败", str(e)))

        return {"text": text_prompts, "image": image_prompts}

    def _add_section(self, parent_layout, title: str, items: list):
        """添加一个提示词分组"""
        section_label = QLabel(title)
        section_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {TEXT_PRIMARY}; margin-top: 8px;")
        parent_layout.addWidget(section_label)

        _mono = QFont("Consolas", 9)
        _mono.setStyleHint(QFont.Monospace)

        for label, text in items:
            item_label = QLabel(label)
            item_label.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY}; margin-top: 4px;")
            parent_layout.addWidget(item_label)

            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setFont(_mono)
            # 根据内容长度调整高度，最小 80 最大 180
            line_count = text.count("\n") + 1
            height = min(max(line_count * 16, 80), 180)
            editor.setFixedHeight(height)
            editor.setPlainText(text)
            editor.setStyleSheet(
                f"background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 6px;"
            )
            parent_layout.addWidget(editor)

    def _on_settings(self):
        """用户点击"去设置修改"：关闭对话框并发信号"""
        self.settings_requested.emit()
        self.reject()  # 关闭对话框，不触发 accept
