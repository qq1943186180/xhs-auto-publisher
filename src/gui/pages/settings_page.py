"""
Settings Page - PyQt-Fluent-Widgets
"""
import json
import logging
import os

from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel, QScrollArea
from PyQt5.QtCore import Qt, pyqtSignal

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, LineEdit, SwitchButton,
    SpinBox, InfoBar
)
from src.gui.styles.theme import (
    TEXT_SECONDARY,
    page_subtitle_style,
    page_title_style,
    section_title_style,
)
from src.gui.utils import PAGE_MARGINS

logger = logging.getLogger(__name__)


class SettingsPage(QWidget):
    """Settings page"""

    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(PAGE_MARGINS)
        main_layout.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("设置")
        title.setStyleSheet(page_title_style())
        header.addWidget(title)
        subtitle = QLabel("配置账号、浏览器、采集和发布参数。")
        subtitle.setStyleSheet(page_subtitle_style())
        header.addWidget(subtitle)
        main_layout.addLayout(header)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(16)

        # API Config card
        api_card = CardWidget(self)
        api_layout = QVBoxLayout(api_card)
        api_layout.setContentsMargins(20, 20, 20, 20)
        api_layout.setSpacing(12)

        api_title = QLabel("账号与 API")
        api_title.setStyleSheet(section_title_style())
        api_layout.addWidget(api_title)

        # OpenAI Key
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("OpenAI Key:"))
        self.openai_key_edit = LineEdit()
        self.openai_key_edit.setEchoMode(LineEdit.Password)
        self.openai_key_edit.setPlaceholderText("sk-...")
        row1.addWidget(self.openai_key_edit)
        api_layout.addLayout(row1)

        # OpenAI Base URL (for proxy / one-api)
        row1b = QHBoxLayout()
        row1b.addWidget(QLabel("OpenAI Base URL:"))
        self.openai_base_edit = LineEdit()
        self.openai_base_edit.setPlaceholderText("https://api.openai.com/v1（留空用默认）")
        row1b.addWidget(self.openai_base_edit)
        api_layout.addLayout(row1b)

        # Kimi Key
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Kimi Key:"))
        self.kimi_key_edit = LineEdit()
        self.kimi_key_edit.setEchoMode(LineEdit.Password)
        self.kimi_key_edit.setPlaceholderText("Kimi API Key")
        row2.addWidget(self.kimi_key_edit)
        api_layout.addLayout(row2)

        layout.addWidget(api_card)

        # Browser Config card
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

        # Collection Config card
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

        # Publish Config card
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

        # Save button
        save_btn = PrimaryPushButton("保存设置")
        save_btn.setFixedHeight(44)
        save_btn.setMinimumWidth(160)
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

    def _on_save(self):
        data = {
            "openai_key": self.openai_key_edit.text(),
            "openai_base_url": self.openai_base_edit.text(),
            "kimi_key": self.kimi_key_edit.text(),
            "headless": self.headless_switch.isChecked(),
            "images_per_product": self.images_per_product_spin.value(),
            "interval": self.interval_spin.value(),
            "max_daily": self.daily_spin.value(),
        }

        # Save API keys to key manager (encrypted)
        try:
            from src.ai.api_key_manager import get_key_manager, Provider
            km = get_key_manager()
            if data["openai_key"] and data["openai_key"] != "••••••••":
                base_url = data.get("openai_base_url") or None
                km.add_key(Provider.OPENAI, data["openai_key"], base_url=base_url)
            if data["kimi_key"]:
                km.add_key(Provider.KIMI, data["kimi_key"])
        except ImportError as e:
            logger.error("API key manager module not found: %s", e)
            InfoBar.error("保存失败", f"API 模块导入失败: {e}", parent=self)
            return
        except AttributeError as e:
            logger.error("API key manager attribute error: %s", e)
            InfoBar.error("保存失败", f"API 配置异常: {e}", parent=self)
            return
        except Exception as e:
            logger.error("Save API keys failed: %s", e)
            InfoBar.error("保存失败", f"API 密钥保存失败: {e}", parent=self)
            return

        # Save other settings to config file
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
            })
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except json.JSONDecodeError as e:
            logger.error("Config file corrupted: %s", e)
            InfoBar.error("保存失败", f"配置文件格式错误: {e}", parent=self)
            return
        except PermissionError as e:
            logger.error("Permission denied writing config: %s", e)
            InfoBar.error("保存失败", f"权限不足: {e}", parent=self)
            return
        except Exception as e:
            logger.error("Save config failed: %s", e)
            InfoBar.error("保存失败", f"配置保存失败: {e}", parent=self)
            return

        self.settings_changed.emit(data)
        InfoBar.success("保存成功", "设置已更新并加密保存", parent=self)

    def load_settings(self):
        """Load saved settings on startup"""
        try:
            from src.ai.api_key_manager import get_key_manager
            km = get_key_manager()
            for entry in km._keys:
                if entry.provider.value == "openai":
                    self.openai_key_edit.setText("••••••••")
                    if entry.base_url:
                        self.openai_base_edit.setText(entry.base_url)
                elif entry.provider.value == "kimi":
                    self.kimi_key_edit.setText("••••••••")
        except ImportError as e:
            logger.warning("API key manager module not found: %s", e)
        except AttributeError as e:
            logger.warning("API key manager attribute error: %s", e)
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
        except json.JSONDecodeError as e:
            logger.warning("Config file corrupted: %s", e)
        except PermissionError as e:
            logger.warning("Permission denied reading config: %s", e)
        except Exception as e:
            logger.warning("Load config failed: %s", e)
