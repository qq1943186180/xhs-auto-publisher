"""
Settings Page - PyQt-Fluent-Widgets
统一 API 配置：一个提供方下拉 + Key / Base URL / Model，类似 Chatbox 风格。
"""
import json
import logging
import os
import threading
import time

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QScrollArea,
    QFileDialog, QMessageBox, QPlainTextEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, LineEdit, SwitchButton,
    SpinBox, InfoBar, ComboBox
)
from src.gui.styles.theme import (
    TEXT_SECONDARY,
    page_subtitle_style,
    page_title_style,
    section_title_style,
    danger_button_style,
)
from src.gui.utils import PAGE_MARGINS
from src.utils.logger import get_logger

logger = get_logger("gui.settings_page")

# 提供方 → 默认 Base URL 和 Model 映射
_PROVIDER_DEFAULTS = {
    "openai": {
        "label": "OpenAI compatible / Mimo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5",
    },
    "kimi": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "deepseek-ai/deepseek-v4-flash",
    },
    "custom": {
        "label": "自定义",
        "base_url": "",
        "model": "",
    },
}

_PROVIDER_KEYS = list(_PROVIDER_DEFAULTS.keys())

# 可编辑提示词：key → 显示名称
_PROMPT_KEYS = [
    ("title_system", "标题生成 · 系统提示词"),
    ("content_system", "文案生成 · 系统提示词（通用）"),
    ("content_template_1", "文案模板 · 日常种草"),
    ("content_template_2", "文案模板 · 真实测评"),
    ("content_template_3", "文案模板 · 搭配灵感"),
    ("content_template_4", "文案模板 · 选购参考"),
    ("content_template_5", "文案模板 · 日常记录"),
    ("direction_system", "文案生成 · 方向提案"),
    ("direction_content_system", "文案生成 · 方向扩写"),
    ("image_style_a", "图片风格 A · 博主随手拍"),
    ("image_style_b", "图片风格 B · 买家秀细节"),
    ("image_style_c", "图片风格 C · 生活随拍"),
    ("image_camera_a", "图片相机 A · iPhone"),
    ("image_camera_b", "图片相机 B · Samsung"),
    ("image_camera_c", "图片相机 C · 便携随拍"),
]


def _get_prompt_defaults() -> dict:
    """获取所有可编辑提示词的默认值"""
    from src.ai.prompt_templates import (
        TITLE_SYSTEM_PROMPT,
        CONTENT_SYSTEM_PROMPT,
        CONTENT_TEMPLATE_1,
        CONTENT_TEMPLATE_2,
        CONTENT_TEMPLATE_3,
        CONTENT_TEMPLATE_4,
        CONTENT_TEMPLATE_5,
        DIRECTION_SYSTEM_PROMPT,
        DIRECTION_CONTENT_SYSTEM_PROMPT,
        IMAGE_STYLE_GUIDES,
        IMAGE_CAMERA_GUIDES,
    )
    return {
        "title_system": TITLE_SYSTEM_PROMPT,
        "content_system": CONTENT_SYSTEM_PROMPT,
        "content_template_1": CONTENT_TEMPLATE_1,
        "content_template_2": CONTENT_TEMPLATE_2,
        "content_template_3": CONTENT_TEMPLATE_3,
        "content_template_4": CONTENT_TEMPLATE_4,
        "content_template_5": CONTENT_TEMPLATE_5,
        "direction_system": DIRECTION_SYSTEM_PROMPT,
        "direction_content_system": DIRECTION_CONTENT_SYSTEM_PROMPT,
        "image_style_a": IMAGE_STYLE_GUIDES["style_a"],
        "image_style_b": IMAGE_STYLE_GUIDES["style_b"],
        "image_style_c": IMAGE_STYLE_GUIDES["style_c"],
        "image_camera_a": IMAGE_CAMERA_GUIDES[0],
        "image_camera_b": IMAGE_CAMERA_GUIDES[1],
        "image_camera_c": IMAGE_CAMERA_GUIDES[2],
    }


class SettingsPage(QWidget):
    """Settings page"""

    settings_changed = pyqtSignal(dict)
    model_test_done = pyqtSignal(bool, str, float)  # success, message, duration_ms
    models_fetch_done = pyqtSignal(bool, object, str, float)  # success, models, message, duration_ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_model_entries = []
        self._fetched_models = []
        self._prompt_texts = {}      # key → 当前编辑中的提示词文本
        self._prompt_defaults = {}   # key → 默认值
        self._current_prompt_index = 0
        self._setup_ui()
        self.model_test_done.connect(self._on_model_test_done, Qt.QueuedConnection)
        self.models_fetch_done.connect(self._on_models_fetch_done, Qt.QueuedConnection)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(PAGE_MARGINS)
        main_layout.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("设置")
        title.setStyleSheet(page_title_style())
        header.addWidget(title)
        subtitle = QLabel("配置 API、浏览器、采集和发布参数。")
        subtitle.setStyleSheet(page_subtitle_style())
        header.addWidget(subtitle)
        main_layout.addLayout(header)

        # Scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(16)

        # ── API Config card ─────────────────────────────────
        api_card = CardWidget(self)
        api_layout = QVBoxLayout(api_card)
        api_layout.setContentsMargins(20, 20, 20, 20)
        api_layout.setSpacing(12)

        api_title = QLabel("API 配置")
        api_title.setStyleSheet(section_title_style())
        api_layout.addWidget(api_title)

        # 提供商下拉
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("模型提供方:"))
        self.provider_combo = ComboBox()
        for key in _PROVIDER_KEYS:
            self.provider_combo.addItem(_PROVIDER_DEFAULTS[key]["label"])
        self.provider_combo.setMinimumWidth(180)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self.provider_combo)
        provider_row.addStretch()
        api_layout.addLayout(provider_row)

        # API Key
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key:"))
        self.api_key_edit = LineEdit()
        self.api_key_edit.setEchoMode(LineEdit.Password)
        self.api_key_edit.setPlaceholderText("输入 API Key")
        key_row.addWidget(self.api_key_edit)
        self.toggle_key_btn = PushButton("显示")
        self.toggle_key_btn.setFixedWidth(60)
        self.toggle_key_btn.clicked.connect(self._toggle_api_key_visibility)
        key_row.addWidget(self.toggle_key_btn)
        api_layout.addLayout(key_row)

        # Base URL
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Base URL:"))
        self.base_url_edit = LineEdit()
        self.base_url_edit.setPlaceholderText(_PROVIDER_DEFAULTS["openai"]["base_url"])
        url_row.addWidget(self.base_url_edit)
        api_layout.addLayout(url_row)

        # Model
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("模型:"))
        self.model_edit = LineEdit()
        self.model_edit.setPlaceholderText(_PROVIDER_DEFAULTS["openai"]["model"])
        model_row.addWidget(self.model_edit)
        api_layout.addLayout(model_row)

        # ── 保存模型按钮 ─────────────────────────────
        save_model_row = QHBoxLayout()
        save_model_btn = PrimaryPushButton("保存模型")
        save_model_btn.setFixedHeight(40)
        save_model_btn.setMinimumWidth(140)
        save_model_btn.clicked.connect(self._on_save_model)
        save_model_row.addWidget(save_model_btn)
        save_model_row.addStretch()
        api_layout.addLayout(save_model_row)

        # ── 获取模型列表 + 测试模型（放在上面）───
        fetch_row = QHBoxLayout()
        self.fetch_models_btn = PushButton("获取模型列表")
        self.fetch_models_btn.clicked.connect(self._on_fetch_models)
        fetch_row.addWidget(self.fetch_models_btn)
        self.fetched_model_combo = ComboBox()
        self.fetched_model_combo.setMinimumWidth(320)
        self.fetched_model_combo.currentIndexChanged.connect(self._on_fetched_model_selected)
        fetch_row.addWidget(self.fetched_model_combo)
        fetch_row.addStretch()
        api_layout.addLayout(fetch_row)

        test_row = QHBoxLayout()
        self.test_model_btn = PushButton("测试模型")
        self.test_model_btn.setFixedHeight(36)
        self.test_model_btn.setMinimumWidth(120)
        self.test_model_btn.clicked.connect(self._on_test_model)
        test_row.addWidget(self.test_model_btn)
        test_row.addStretch()
        api_layout.addLayout(test_row)

        # ── 已保存模型（放在下面）───
        saved_row = QHBoxLayout()
        saved_row.addWidget(QLabel("已保存模型:"))
        self.saved_model_combo = ComboBox()
        self.saved_model_combo.setMinimumWidth(320)
        self.saved_model_combo.currentIndexChanged.connect(self._on_saved_model_selected)
        saved_row.addWidget(self.saved_model_combo)
        primary_btn = PushButton("设为主模型")
        primary_btn.clicked.connect(self._on_set_primary_model)
        saved_row.addWidget(primary_btn)
        delete_model_btn = PushButton("删除模型")
        delete_model_btn.clicked.connect(self._on_delete_model)
        saved_row.addWidget(delete_model_btn)
        api_layout.addLayout(saved_row)

        layout.addWidget(api_card)

        # ── Browser Config card ─────────────────────────────
        browser_card = CardWidget(self)
        browser_layout = QVBoxLayout(browser_card)
        browser_layout.setContentsMargins(20, 20, 20, 20)
        browser_layout.setSpacing(12)

        browser_title = QLabel("浏览器")
        browser_title.setStyleSheet(section_title_style())
        browser_layout.addWidget(browser_title)

        headless_row = QHBoxLayout()
        headless_row.addWidget(QLabel("无头模式:"))
        self.headless_switch = SwitchButton()
        headless_row.addWidget(self.headless_switch)
        headless_row.addStretch()
        browser_layout.addLayout(headless_row)

        layout.addWidget(browser_card)

        # ── Collection Config card ──────────────────────────
        collect_card = CardWidget(self)
        collect_layout = QVBoxLayout(collect_card)
        collect_layout.setContentsMargins(20, 20, 20, 20)
        collect_layout.setSpacing(12)

        collect_title = QLabel("采集")
        collect_title.setStyleSheet(section_title_style())
        collect_layout.addWidget(collect_title)

        images_row = QHBoxLayout()
        images_row.addWidget(QLabel("每商品采集图片数:"))
        self.images_per_product_spin = SpinBox()
        self.images_per_product_spin.setRange(1, 9)
        self.images_per_product_spin.setValue(5)
        images_row.addWidget(self.images_per_product_spin)
        images_hint = QLabel("默认 5 张，用于任务列表和采集命令")
        images_hint.setStyleSheet(f"color: {TEXT_SECONDARY};")
        images_row.addWidget(images_hint)
        images_row.addStretch()
        collect_layout.addLayout(images_row)

        layout.addWidget(collect_card)

        # ── Publish Config card ─────────────────────────────
        publish_card = CardWidget(self)
        publish_layout = QVBoxLayout(publish_card)
        publish_layout.setContentsMargins(20, 20, 20, 20)
        publish_layout.setSpacing(12)

        publish_title = QLabel("发布")
        publish_title.setStyleSheet(section_title_style())
        publish_layout.addWidget(publish_title)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("发布间隔(秒):"))
        self.interval_spin = SpinBox()
        self.interval_spin.setRange(30, 1800)
        self.interval_spin.setValue(300)
        interval_row.addWidget(self.interval_spin)
        interval_row.addStretch()
        publish_layout.addLayout(interval_row)

        daily_row = QHBoxLayout()
        daily_row.addWidget(QLabel("每日最大发布:"))
        self.daily_spin = SpinBox()
        self.daily_spin.setRange(1, 50)
        self.daily_spin.setValue(10)
        daily_row.addWidget(self.daily_spin)
        daily_row.addStretch()
        publish_layout.addLayout(daily_row)

        layout.addWidget(publish_card)

        # ── Prompt Config card ──────────────────────────
        self.prompt_card = CardWidget(self)
        prompt_layout = QVBoxLayout(self.prompt_card)
        prompt_layout.setContentsMargins(20, 20, 20, 20)
        prompt_layout.setSpacing(12)

        prompt_title = QLabel("提示词")
        prompt_title.setStyleSheet(section_title_style())
        prompt_layout.addWidget(prompt_title)

        prompt_hint = QLabel("自定义文案生成和图片生成的提示词。留空或恢复默认后不覆盖原始模板。")
        prompt_hint.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        prompt_layout.addWidget(prompt_hint)

        # 选择要编辑的提示词
        prompt_select_row = QHBoxLayout()
        prompt_select_row.addWidget(QLabel("选择提示词:"))
        self.prompt_combo = ComboBox()
        for _key, label in _PROMPT_KEYS:
            self.prompt_combo.addItem(label)
        self.prompt_combo.setMinimumWidth(260)
        self.prompt_combo.currentIndexChanged.connect(self._on_prompt_selected)
        prompt_select_row.addWidget(self.prompt_combo)
        prompt_select_row.addStretch()
        prompt_layout.addLayout(prompt_select_row)

        # 编辑区
        from PyQt5.QtGui import QFont as _QFont
        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setFixedHeight(300)
        self.prompt_editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        _mono = _QFont("Consolas", 10)
        _mono.setStyleHint(_QFont.Monospace)
        self.prompt_editor.setFont(_mono)
        self.prompt_editor.textChanged.connect(self._update_prompt_char_count)
        prompt_layout.addWidget(self.prompt_editor)

        # 底部按钮行
        prompt_btn_row = QHBoxLayout()
        reset_prompt_btn = PushButton("恢复默认")
        reset_prompt_btn.clicked.connect(self._on_reset_prompt)
        prompt_btn_row.addWidget(reset_prompt_btn)

        reset_all_prompts_btn = PushButton("全部恢复默认")
        reset_all_prompts_btn.clicked.connect(self._on_reset_all_prompts)
        prompt_btn_row.addWidget(reset_all_prompts_btn)

        prompt_btn_row.addStretch()
        self.prompt_char_label = QLabel("")
        self.prompt_char_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        prompt_btn_row.addWidget(self.prompt_char_label)
        prompt_layout.addLayout(prompt_btn_row)

        layout.addWidget(self.prompt_card)

        # ── Data Management card ────────────────────────────
        data_card = CardWidget(self)
        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(20, 20, 20, 20)
        data_layout.setSpacing(12)

        data_title = QLabel("数据管理")
        data_title.setStyleSheet(section_title_style())
        data_layout.addWidget(data_title)

        data_btn_row = QHBoxLayout()
        backup_btn = PushButton("备份数据")
        backup_btn.setFixedHeight(36)
        backup_btn.clicked.connect(self._on_backup)
        data_btn_row.addWidget(backup_btn)

        restore_btn = PushButton("恢复数据")
        restore_btn.setFixedHeight(36)
        restore_btn.clicked.connect(self._on_restore)
        data_btn_row.addWidget(restore_btn)

        clean_btn = PushButton("清理临时文件")
        clean_btn.setFixedHeight(36)
        clean_btn.clicked.connect(self._on_clean_temp)
        data_btn_row.addWidget(clean_btn)

        data_btn_row.addStretch()
        data_layout.addLayout(data_btn_row)

        data_hint = QLabel("备份包含数据库、配置、API 密钥和采集数据。恢复前会自动保存当前数据。")
        data_hint.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        data_layout.addWidget(data_hint)

        layout.addWidget(data_card)

        # ── Save / Delete buttons ────────────────────
        btn_row = QHBoxLayout()
        save_btn = PrimaryPushButton("保存设置")
        save_btn.setFixedHeight(44)
        save_btn.setMinimumWidth(160)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        delete_btn = PushButton("删除配置")
        delete_btn.setFixedHeight(44)
        delete_btn.setMinimumWidth(120)
        delete_btn.clicked.connect(self._on_delete)
        delete_btn.setStyleSheet(danger_button_style())
        btn_row.addWidget(delete_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()
        self.scroll.setWidget(scroll_widget)
        main_layout.addWidget(self.scroll)

    # ── API Key 可见性切换 ────────────────────────────────────

    def _toggle_api_key_visibility(self):
        """切换 API Key 输入框的明文/密文显示"""
        if self.api_key_edit.echoMode() == LineEdit.Password:
            self.api_key_edit.setEchoMode(LineEdit.Normal)
            self.toggle_key_btn.setText("隐藏")
        else:
            self.api_key_edit.setEchoMode(LineEdit.Password)
            self.toggle_key_btn.setText("显示")

    # ── 提供方切换 ──────────────────────────────────────────

    def _get_selected_provider_key(self) -> str:
        """获取当前选中的提供方 key（openai/kimi/nvidia/custom）"""
        idx = self.provider_combo.currentIndex()
        if 0 <= idx < len(_PROVIDER_KEYS):
            return _PROVIDER_KEYS[idx]
        return "openai"

    def _on_provider_changed(self, index: int):
        """切换提供方时更新 Base URL 和 Model 的 placeholder，并加载该提供方的已有密钥"""
        key = self._get_selected_provider_key()
        defaults = _PROVIDER_DEFAULTS.get(key, _PROVIDER_DEFAULTS["custom"])
        self.base_url_edit.setPlaceholderText(defaults["base_url"] or "输入 API Base URL")
        self.model_edit.setPlaceholderText(defaults["model"] or "输入模型名称")

        # 查找该提供方已保存的密钥并加载
        try:
            from src.ai.api_key_manager import get_key_manager, Provider
            km = get_key_manager()
            provider_enum = Provider(key) if key in [p.value for p in Provider] else None
            existing = None
            if provider_enum:
                for item in km.list_keys():
                    if item.get("provider") == provider_enum.value:
                        existing = item
                        break
            if existing:
                self.api_key_edit.setText(existing.get("api_key_masked", ""))
                self.base_url_edit.setText(existing.get("base_url", "") or defaults.get("base_url", ""))
                self.model_edit.setText(existing.get("model", "") or defaults.get("model", ""))
                logger.info("Loaded existing key for provider %s", key)
            else:
                # 没有已有密钥，清空并填入默认值
                self.api_key_edit.clear()
                if not self.base_url_edit.text():
                    self.base_url_edit.setText(defaults["base_url"])
                if not self.model_edit.text():
                    self.model_edit.setText(defaults["model"])
        except Exception as e:
            logger.warning("Failed to load existing key for provider: %s", e)
            if not self.base_url_edit.text():
                self.base_url_edit.setText(defaults["base_url"])
            if not self.model_edit.text():
                self.model_edit.setText(defaults["model"])

    # ── 保存 ────────────────────────────────────────────────

    def _refresh_saved_models(self):
        self.saved_model_combo.blockSignals(True)
        self.saved_model_combo.clear()
        self._saved_model_entries = []
        try:
            from src.ai.api_key_manager import get_key_manager
            km = get_key_manager()
            for item in km.list_keys():
                self._saved_model_entries.append(item)
                prefix = "主模型 · " if item.get("index") == 0 else ""
                state = "" if item.get("enabled") else " · 已停用"
                label = (
                    f"{prefix}{item.get('provider')}/{item.get('model')} "
                    f"({item.get('base_url')}, {item.get('key_masked')}){state}"
                )
                self.saved_model_combo.addItem(label)
        except Exception as e:
            logger.warning("Load saved models failed: %s", e)
        self.saved_model_combo.blockSignals(False)

    def _selected_saved_model(self) -> dict | None:
        idx = self.saved_model_combo.currentIndex()
        if 0 <= idx < len(self._saved_model_entries):
            return self._saved_model_entries[idx]
        return None

    def _apply_model_entry(self, entry: dict):
        provider = entry.get("provider", "openai")
        provider_index = _PROVIDER_KEYS.index(provider) if provider in _PROVIDER_KEYS else 0
        self.provider_combo.setCurrentIndex(provider_index)
        self.api_key_edit.setText("••••••••")
        self.base_url_edit.setText(entry.get("base_url") or "")
        self.model_edit.setText(entry.get("model") or "")

    def _on_saved_model_selected(self, index: int):
        entry = self._selected_saved_model()
        if entry:
            self._apply_model_entry(entry)

    def _on_set_primary_model(self):
        entry = self._selected_saved_model()
        if not entry:
            InfoBar.warning("提示", "请先选择一个已保存模型", parent=self)
            return
        try:
            from src.ai.api_key_manager import get_key_manager
            ok = get_key_manager().set_primary_model(
                entry["provider"],
                entry["api_key"],
                entry.get("base_url"),
                entry.get("model"),
            )
            if ok:
                self._refresh_saved_models()
                InfoBar.success("已设为主模型", entry.get("model", ""), parent=self)
            else:
                InfoBar.warning("未找到模型", "这个模型可能已经被删除，请刷新后再试", parent=self)
        except Exception as e:
            logger.error("Set primary model failed: %s", e)
            InfoBar.error("设置失败", str(e), parent=self)

    def _on_delete_model(self):
        entry = self._selected_saved_model()
        if not entry:
            InfoBar.warning("提示", "请先选择一个已保存模型", parent=self)
            return
        try:
            from src.ai.api_key_manager import get_key_manager
            ok = get_key_manager().remove_model(
                entry["provider"],
                entry["api_key"],
                entry.get("base_url"),
                entry.get("model"),
            )
            if ok:
                self._refresh_saved_models()
                InfoBar.success("已删除", entry.get("model", ""), parent=self)
            else:
                InfoBar.warning("未删除", "这个模型可能已经不存在", parent=self)
        except Exception as e:
            logger.error("Delete model failed: %s", e)
            InfoBar.error("删除失败", str(e), parent=self)

    def _on_fetch_models(self):
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        if api_key == "••••••••":
            entry = self._selected_saved_model()
            api_key = (entry or {}).get("api_key", "")
        if not api_key or not base_url:
            InfoBar.warning("缺少信息", "请先填写 API Key 和 Base URL", parent=self)
            return

        self.fetch_models_btn.setEnabled(False)
        self.fetch_models_btn.setText("获取中…")

        def _worker():
            start = time.time()
            try:
                from src.ai.api_key_manager import get_key_manager
                models = get_key_manager().fetch_models(api_key, base_url)
                elapsed = (time.time() - start) * 1000
                self.models_fetch_done.emit(True, models, "", elapsed)
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                self.models_fetch_done.emit(False, [], str(e), elapsed)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_models_fetch_done(self, success: bool, models_obj, message: str, duration_ms: float):
        self.fetch_models_btn.setEnabled(True)
        self.fetch_models_btn.setText("获取模型列表")
        models = list(models_obj or [])
        if success:
            self.fetched_model_combo.clear()
            self._fetched_models = models
            for model in models:
                self.fetched_model_combo.addItem(model)
            if models:
                self.model_edit.setText(models[0])
                InfoBar.success("获取成功", f"找到 {len(models)} 个模型，耗时 {duration_ms:.0f}ms", parent=self)
            else:
                InfoBar.warning("没有模型", "接口可访问，但没有返回模型列表", parent=self)
        else:
            logger.error("Fetch models failed: %s", message)
            InfoBar.error("获取失败", f"请检查 Key、Base URL 或网络：{message}", parent=self)

    def _on_fetched_model_selected(self, index: int):
        if 0 <= index < len(self._fetched_models):
            self.model_edit.setText(self._fetched_models[index])

    # ── 保存单个模型 ────────────────────────────────

    def _on_save_model(self):
        """保存当前填写的模型配置到已保存列表"""
        provider_key = self._get_selected_provider_key()
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        model = self.model_edit.text().strip()

        is_masked = api_key in {"••••••••", "********"}
        if is_masked and not self._selected_saved_model():
            InfoBar.warning("缺少 API Key", "请输入 API Key 或从已保存模型中选择", parent=self)
            return
        if not model:
            InfoBar.warning("缺少模型", "请填写模型名称", parent=self)
            return

        try:
            from src.ai.api_key_manager import get_key_manager, Provider

            provider_map = {
                "openai": Provider.OPENAI,
                "kimi": Provider.KIMI,
                "nvidia": Provider.NVIDIA,
                "custom": Provider.OPENAI,
            }
            provider_enum = provider_map.get(provider_key, Provider.OPENAI)
            km = get_key_manager()

            real_key = api_key
            if is_masked:
                entry = self._selected_saved_model()
                real_key = (entry or {}).get("api_key", "")

            if not real_key or len(real_key) < 12:
                InfoBar.error("无效 API Key", "API Key 长度不足，请重新填写", parent=self)
                return

            added = km.add_key(
                provider_enum,
                real_key,
                base_url=base_url or None,
                model=model or None,
            )
            if not added:
                km.update_key(
                    provider_enum,
                    real_key,
                    base_url=base_url or None,
                    model=model or None,
                )
            km.set_primary_model(provider_enum, real_key, base_url or None, model or None)
            self._refresh_saved_models()
            InfoBar.success("模型已保存", f"{provider_key}/{model} 已保存并设为主模型", parent=self)
        except Exception as e:
            logger.error("Save model failed: %s", e)
            InfoBar.error("保存失败", str(e), parent=self)

    def _on_save(self):
        provider_key = self._get_selected_provider_key()
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        model = self.model_edit.text().strip()

        # Validate: must have a real key or a saved model selected
        is_masked = api_key in {"••••••••", "********"}
        selected_entry = self._selected_saved_model()
        if (not api_key or is_masked) and not selected_entry:
            InfoBar.error("缺少 API Key", "请输入 API Key 或选择一个已保存的模型", parent=self)
            return

        # Validate: base_url must start with http if not empty
        if base_url and not base_url.startswith("http"):
            InfoBar.error("Base URL 无效", "Base URL 必须以 http:// 或 https:// 开头", parent=self)
            return

        data = {
            "provider": provider_key,
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "headless": self.headless_switch.isChecked(),
            "images_per_product": self.images_per_product_spin.value(),
            "interval": self.interval_spin.value(),
            "max_daily": self.daily_spin.value(),
        }

        try:
            from src.ai.api_key_manager import get_key_manager, Provider

            provider_map = {
                "openai": Provider.OPENAI,
                "kimi": Provider.KIMI,
                "nvidia": Provider.NVIDIA,
                "custom": Provider.OPENAI,
            }
            provider_enum = provider_map.get(provider_key, Provider.OPENAI)
            km = get_key_manager()
            selected_entry = self._selected_saved_model()
            has_real_key = api_key and api_key not in {"••••••••", "********"} and len(api_key) >= 12

            if has_real_key:
                added = km.add_key(
                    provider_enum,
                    api_key,
                    base_url=base_url or None,
                    model=model or None,
                )
                if not added:
                    km.update_key(
                        provider_enum,
                        api_key,
                        base_url=base_url or None,
                        model=model or None,
                    )
                km.set_primary_model(provider_enum, api_key, base_url or None, model or None)
            elif selected_entry and (base_url or model):
                km.update_key(
                    selected_entry["provider"],
                    selected_entry["api_key"],
                    base_url=base_url or None,
                    model=model or None,
                    old_base_url=selected_entry.get("base_url"),
                    old_model=selected_entry.get("model"),
                )
                km.set_primary_model(
                    selected_entry["provider"],
                    selected_entry["api_key"],
                    base_url or None,
                    model or None,
                )
        except ImportError as e:
            logger.error("API key manager module not found: %s", e)
            InfoBar.error("保存失败", f"API 模块导入失败: {e}", parent=self)
            return
        except Exception as e:
            logger.error("Save API keys failed: %s", e)
            InfoBar.error("保存失败", f"API 密钥保存失败: {e}", parent=self)
            return

        config_path = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "config.json")
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            config = {}
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            config.update({
                "headless": data["headless"],
                "images_per_product": data["images_per_product"],
                "publish_interval": data["interval"],
                "max_daily": data["max_daily"],
                "prompts": self._collect_prompts_for_save(),
            })
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Save config failed: %s", e)
            InfoBar.error("保存失败", f"配置保存失败: {e}", parent=self)
            return

        self._refresh_saved_models()
        self.settings_changed.emit(data)
        InfoBar.success("保存成功", "模型配置已加密保存，并设为主模型", parent=self)
    def _on_delete(self):
        """删除当前提供方的已保存 API Key"""
        provider_key = self._get_selected_provider_key()
        label = _PROVIDER_DEFAULTS.get(provider_key, {}).get("label", provider_key)

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除 {label} 的所有 API Key 配置吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            from src.ai.api_key_manager import get_key_manager, Provider

            provider_map = {
                "openai": Provider.OPENAI,
                "kimi": Provider.KIMI,
                "nvidia": Provider.NVIDIA,
                "custom": Provider.OPENAI,
            }
            provider_key = self._get_selected_provider_key()
            provider_enum = provider_map.get(provider_key, Provider.OPENAI)

            km = get_key_manager()
            removed = False
            for entry in list(km._keys):
                if entry.provider == provider_enum:
                    km.remove_key(entry.api_key)
                    removed = True

            if removed:
                # 清空输入框
                self.api_key_edit.clear()
                self.base_url_edit.clear()
                self.model_edit.clear()
                InfoBar.success("已删除", f"{label} 的 API 配置已移除", parent=self)
            else:
                InfoBar.warning("提示", "当前提供方没有已保存的配置", parent=self)

        except Exception as e:
            logger.error("Delete API key failed: %s", e)
            InfoBar.error("删除失败", str(e), parent=self)

    # ── 模型健康检查 ────────────────────────────────────────

    def _on_test_model(self):
        """测试当前模型配置是否可用"""
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        model = self.model_edit.text().strip()

        # 如果 key 被遮罩，从已保存模型中取真实 key
        if api_key in ("••••••••", "********"):
            entry = self._selected_saved_model()
            api_key = (entry or {}).get("api_key", "")

        if not api_key or not base_url or not model:
            InfoBar.warning("缺少信息", "请先填写 API Key、Base URL 和模型名称", parent=self)
            return

        self.test_model_btn.setEnabled(False)
        self.test_model_btn.setText("测试中…")

        def _worker():
            start = time.time()
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key, base_url=base_url, timeout=15)
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a test assistant."},
                        {"role": "user", "content": "Reply with exactly: ok"},
                    ],
                    max_tokens=10,
                )
                text = (resp.choices[0].message.content or "").strip()
                elapsed = (time.time() - start) * 1000
                self.model_test_done.emit(True, f"模型可用，回复: {text[:20]}", elapsed)
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                self.model_test_done.emit(False, str(e), elapsed)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_model_test_done(self, success: bool, message: str, duration_ms: float):
        """模型测试完成回调（由信号触发，在主线程）"""
        self.test_model_btn.setEnabled(True)
        self.test_model_btn.setText("测试模型")
        if success:
            InfoBar.success("测试通过", f"{message}，耗时 {duration_ms:.0f}ms", parent=self)
        else:
            InfoBar.error("测试失败", f"{message}（{duration_ms:.0f}ms）", parent=self)

    # ── 数据备份 ────────────────────────────────────────────

    def _on_backup(self):
        """备份数据到用户选择的 zip 文件"""
        path, _ = QFileDialog.getSaveFileName(
            self, "备份数据", "xhs_backup.zip", "Zip 文件 (*.zip)",
        )
        if not path:
            return
        try:
            from src.services.backup_service import create_backup
            result = create_backup(path)
            InfoBar.success(
                "备份完成",
                f"{result['size_mb']} MB，{len(result['files'])} 个文件",
                parent=self,
            )
        except Exception as e:
            logger.error("Backup failed: %s", e)
            InfoBar.error("备份失败", str(e), parent=self)

    def _on_restore(self):
        """从 zip 恢复数据"""
        reply = QMessageBox.warning(
            self, "恢复数据",
            "恢复将覆盖当前数据（恢复前会自动备份）。\n确定继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", "", "Zip 文件 (*.zip)",
        )
        if not path:
            return
        try:
            from src.services.backup_service import restore_backup
            result = restore_backup(path)
            InfoBar.success(
                "恢复完成",
                f"已恢复 {len(result['restored'])} 项数据",
                parent=self,
            )
        except Exception as e:
            logger.error("Restore failed: %s", e)
            InfoBar.error("恢复失败", str(e), parent=self)

    # ── 清理临时文件 ────────────────────────────────────────

    def _on_clean_temp(self):
        """扫描并清理临时文件"""
        try:
            from src.services.cleanup_service import scan_temp_files, clean_temp_files
            scan = scan_temp_files()
            total_mb = scan["total_mb"]
            count = len(scan["items"])

            if count == 0:
                InfoBar.info("提示", "没有需要清理的临时文件", parent=self)
                return

            reply = QMessageBox.information(
                self, "清理临时文件",
                f"发现 {count} 个临时目录/文件，共 {total_mb} MB。\n确定清理？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            result = clean_temp_files()
            InfoBar.success(
                "清理完成",
                f"删除 {result['files_deleted']} 个文件，释放 {result['space_freed_mb']} MB",
                parent=self,
            )
        except Exception as e:
            logger.error("Cleanup failed: %s", e)
            InfoBar.error("清理失败", str(e), parent=self)

    # ── 加载 ────────────────────────────────────────────────

    # ── 提示词编辑 ──────────────────────────────────────

    def _current_prompt_key(self) -> str:
        """获取当前选中提示词的 key"""
        idx = self.prompt_combo.currentIndex()
        if 0 <= idx < len(_PROMPT_KEYS):
            return _PROMPT_KEYS[idx][0]
        return _PROMPT_KEYS[0][0]

    def _save_current_prompt_text(self):
        """将编辑器当前内容保存到 _prompt_texts"""
        key = self._current_prompt_key()
        self._prompt_texts[key] = self.prompt_editor.toPlainText()

    def _load_prompt_into_editor(self, key: str):
        """将指定 key 的提示词加载到编辑器"""
        text = self._prompt_texts.get(key, "")
        self.prompt_editor.setPlainText(text)
        self._update_prompt_char_count()

    def _update_prompt_char_count(self):
        """更新字数统计标签"""
        text = self.prompt_editor.toPlainText()
        self.prompt_char_label.setText(f"{len(text)} 字符")

    def _on_prompt_selected(self, index: int):
        """ComboBox 切换时：保存当前 → 加载新的"""
        # 先保存当前编辑中的文本
        if self._prompt_texts:
            old_key = _PROMPT_KEYS[self._current_prompt_index][0]
            self._prompt_texts[old_key] = self.prompt_editor.toPlainText()
        self._current_prompt_index = index
        # 加载新选中的
        key = self._current_prompt_key()
        self._load_prompt_into_editor(key)

    def _on_reset_prompt(self):
        """恢复当前提示词为默认值"""
        key = self._current_prompt_key()
        default = self._prompt_defaults.get(key, "")
        self._prompt_texts[key] = default
        self.prompt_editor.setPlainText(default)
        InfoBar.success("已恢复默认", _PROMPT_KEYS[self._current_prompt_index][1], parent=self)

    def _on_reset_all_prompts(self):
        """恢复所有提示词为默认值"""
        reply = QMessageBox.question(
            self, "确认",
            "确定将所有提示词恢复为默认值吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._prompt_texts = dict(self._prompt_defaults)
        self._load_prompt_into_editor(self._current_prompt_key())
        InfoBar.success("已恢复", "所有提示词已恢复默认", parent=self)

    def _collect_prompts_for_save(self) -> dict:
        """收集所有自定义提示词（与默认不同的才保存）"""
        # 先把当前编辑器的内容存回
        self._save_current_prompt_text()
        custom = {}
        for key, _label in _PROMPT_KEYS:
            text = self._prompt_texts.get(key, "")
            default = self._prompt_defaults.get(key, "")
            if text and text.strip() != default.strip():
                custom[key] = text
        return custom

    def load_prompts(self):
        """加载提示词：默认值 + config 中的自定义覆盖"""
        defaults = _get_prompt_defaults()
        self._prompt_defaults = dict(defaults)
        self._prompt_texts = dict(defaults)

        # 从 config 读取自定义覆盖
        config_path = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "config.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                saved_prompts = config.get("prompts", {})
                if isinstance(saved_prompts, dict):
                    for key in saved_prompts:
                        if key in self._prompt_texts and saved_prompts[key]:
                            self._prompt_texts[key] = saved_prompts[key]
        except Exception as e:
            logger.warning("Load prompts failed: %s", e)

        # 加载第一个到编辑器
        self._current_prompt_index = 0
        self._load_prompt_into_editor(self._current_prompt_key())

    def scroll_to_prompts(self):
        """滚动到提示词卡片位置"""
        try:
            from PyQt5.QtCore import QPoint
            widget = self.scroll.widget()
            if widget and self.prompt_card:
                y = self.prompt_card.mapTo(widget, QPoint(0, 0)).y()
                self.scroll.verticalScrollBar().setValue(max(0, y - 20))
        except Exception as e:
            logger.warning("Scroll to prompts failed: %s", e)

    def load_settings(self):
        """Load saved settings on startup"""
        try:
            from src.ai.api_key_manager import get_key_manager, Provider
            km = get_key_manager()
            self._refresh_saved_models()
            if not km._keys:
                return
            # 加载第一条 key 的配置
            entry = km._keys[0]
            # 设置提供方下拉
            provider_map = {
                Provider.OPENAI: 0,   # "openai"
                Provider.KIMI: 1,     # "kimi"
                Provider.NVIDIA: 2,   # "nvidia"
            }
            idx = provider_map.get(entry.provider, 0)
            self.provider_combo.setCurrentIndex(idx)

            self.api_key_edit.setText("••••••••")
            if entry.base_url:
                self.base_url_edit.setText(entry.base_url)
            if entry.model:
                self.model_edit.setText(entry.model)
        except ImportError as e:
            logger.warning("API key manager module not found: %s", e)
        except Exception as e:
            logger.warning("Load API keys failed: %s", e)

        config_path = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "config.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self.headless_switch.setChecked(config.get("headless", False))
                self.images_per_product_spin.setValue(config.get("images_per_product", 5))
                self.interval_spin.setValue(config.get("publish_interval", 300))
                self.daily_spin.setValue(config.get("max_daily", 10))
        except Exception as e:
            logger.warning("Load config failed: %s", e)

        # 加载提示词
        self.load_prompts()
