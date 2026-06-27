"""
生成历史页面 - 查看所有 AI 生成记录
从 generated_notes 表读取，支持查看/重新发布/删除
"""
import logging
import os
from datetime import datetime

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QWidget, QScrollArea,
    QGridLayout, QMessageBox, QPlainTextEdit, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, InfoBar,
    SegmentedWidget, CheckBox, ProgressBar, TableWidget,
)
from src.gui.styles.theme import (
    BORDER, ERROR, PRIMARY, SUCCESS, SURFACE_ALT,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
    page_subtitle_style, page_title_style, placeholder_style,
)
from src.gui.utils import PAGE_MARGINS
from src.gui.workers.image_loader import AsyncImageLoader, _create_placeholder_pixmap
from src.utils.logger import get_logger

logger = get_logger("gui.history_page")


class HistoryPage(QWidget):
    """生成历史页面"""

    history_selected = pyqtSignal(dict)  # 选中某条记录进行编辑
    publish_requested = pyqtSignal(dict)  # 请求发布某条记录

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._selected_ids = set()
        self._thumb_labels = {}
        self._card_checkboxes = {}
        self._next_thumb_index = 1
        self._view_mode = "card"
        self._image_loader = AsyncImageLoader(self)
        self._image_loader.image_loaded.connect(self._on_batch_image_loaded)
        self._setup_ui()
        QTimer.singleShot(500, self._load_history)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGINS)
        layout.setSpacing(16)

        # Header
        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("生成历史")
        title.setStyleSheet(page_title_style())
        header.addWidget(title)
        subtitle = QLabel("查看所有 AI 生成记录，支持重新编辑、发布或删除。")
        subtitle.setStyleSheet(page_subtitle_style())
        header.addWidget(subtitle)
        layout.addLayout(header)

        # Summary cards
        self.summary_card = CardWidget(self)
        summary_layout = QHBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.setSpacing(12)
        self.summary_labels = {}
        for key, label in (
            ("total", "全部"),
            ("today", "今日"),
            ("draft", "草稿"),
            ("published", "已发布"),
        ):
            box = QLabel(f"{label}\n0")
            box.setAlignment(Qt.AlignCenter)
            box.setMinimumWidth(100)
            box.setStyleSheet(
                f"background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 8px; "
                f"padding: 8px; color: {TEXT_PRIMARY}; font-weight: 700;"
            )
            summary_layout.addWidget(box)
            self.summary_labels[key] = box
        summary_layout.addStretch()
        layout.addWidget(self.summary_card)

        # Toolbar
        toolbar_card = CardWidget(self)
        toolbar = QHBoxLayout(toolbar_card)
        toolbar.setContentsMargins(16, 12, 16, 12)
        toolbar.setSpacing(12)

        self.count_label = QLabel("共 0 条记录")
        self.count_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px;")
        toolbar.addWidget(self.count_label)

        self.view_switch = SegmentedWidget(self)
        self.view_switch.addItem("card", "卡片")
        self.view_switch.addItem("table", "表格")
        self.view_switch.setCurrentItem(self._view_mode)
        self.view_switch.currentItemChanged.connect(self._on_view_mode_changed)
        toolbar.addWidget(self.view_switch)

        toolbar.addStretch()

        self.select_all_cb = CheckBox("全选")
        self.select_all_cb.setChecked(False)
        self.select_all_cb.stateChanged.connect(self._on_select_all)
        toolbar.addWidget(self.select_all_cb)

        self.selected_label = QLabel("已选 0 条")
        self.selected_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        toolbar.addWidget(self.selected_label)

        refresh_btn = PushButton("刷新")
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(self._load_history)
        toolbar.addWidget(refresh_btn)

        self.delete_btn = PushButton("删除选中")
        self.delete_btn.setFixedHeight(36)
        self.delete_btn.setStyleSheet(f"color: {ERROR};")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        toolbar.addWidget(self.delete_btn)

        layout.addWidget(toolbar_card)

        # Card scroll area
        self.card_scroll = QScrollArea(self)
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QScrollArea.NoFrame)
        self.card_container = QWidget()
        self.card_grid = QGridLayout(self.card_container)
        self.card_grid.setContentsMargins(0, 0, 0, 0)
        self.card_grid.setSpacing(14)
        self.card_scroll.setWidget(self.card_container)
        layout.addWidget(self.card_scroll)

        # Table (hidden by default)
        self.table = TableWidget(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["", "标题", "产品", "状态", "创建时间", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 140)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table)
        self.table.hide()

        self._apply_view_mode()

    def _on_view_mode_changed(self, key: str):
        self._view_mode = key
        self._apply_view_mode()
        if self._items and key == "card":
            self._load_cards()

    def _apply_view_mode(self):
        if self._view_mode == "card":
            self.card_scroll.setVisible(True)
            self.table.setVisible(False)
        else:
            self.card_scroll.setVisible(False)
            self.table.setVisible(True)

    def _on_batch_image_loaded(self, index: int, path: str, pixmap):
        """Update any thumbnail label registered for this async image request."""
        label = self._thumb_labels.pop(index, None)
        if not label:
            return
        try:
            label.setPixmap(pixmap)
        except RuntimeError:
            pass

    def _load_history(self):
        """从数据库加载生成历史"""
        try:
            from src.database.db_manager import get_db_manager
            from src.database.models import GeneratedNote

            db = get_db_manager()
            with db.get_session() as session:
                notes = session.query(GeneratedNote).order_by(
                    GeneratedNote.created_at.desc()
                ).all()
                self._items = [n.to_dict() for n in notes]

            self._update_summary()
            if self._view_mode == "card":
                self._load_cards()
            else:
                self._load_table()
            self.count_label.setText(f"共 {len(self._items)} 条记录")
        except Exception as e:
            logger.error("Load history failed: %s", e)
            InfoBar.error("加载失败", str(e), parent=self)

    def _update_summary(self):
        total = len(self._items)
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = sum(
            1 for item in self._items
            if item.get("created_at", "").startswith(today)
        )
        draft_count = sum(1 for item in self._items if item.get("status") == "draft")
        published_count = sum(1 for item in self._items if item.get("status") == "published")

        self.summary_labels["total"].setText(f"全部\n{total}")
        self.summary_labels["today"].setText(f"今日\n{today_count}")
        self.summary_labels["draft"].setText(f"草稿\n{draft_count}")
        self.summary_labels["published"].setText(f"已发布\n{published_count}")

    def _load_cards(self):
        """渲染卡片网格"""
        while self.card_grid.count():
            w = self.card_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._card_checkboxes.clear()
        self._thumb_labels.clear()
        self._selected_ids.clear()
        self.select_all_cb.blockSignals(True)
        self.select_all_cb.setChecked(False)
        self.select_all_cb.blockSignals(False)
        self.selected_label.setText("已选 0 条")

        for i, item in enumerate(self._items):
            row = i // 3
            col = i % 3
            card = self._create_item_card(item, i)
            self.card_grid.addWidget(card, row, col)

        # 添加伸缩项
        if self._items:
            self.card_grid.addWidget(QWidget(), (len(self._items) // 3) + 1, 0)

    def _create_item_card(self, item: dict, index: int) -> CardWidget:
        card = CardWidget()
        card.setFixedHeight(220)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        # 顶部：复选框 + 状态
        top = QHBoxLayout()
        cb = CheckBox()
        cb.setFixedSize(20, 20)
        cb.stateChanged.connect(lambda s, iid=item["id"]: self._on_item_checked(iid, s))
        self._card_checkboxes[item["id"]] = cb
        top.addWidget(cb)

        status = item.get("status", "draft")
        status_label = QLabel(status)
        color = SUCCESS if status == "published" else (PRIMARY if status == "draft" else ERROR)
        status_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
        top.addWidget(status_label)
        top.addStretch()

        # 时间
        created = item.get("created_at", "")[:10] if item.get("created_at") else ""
        time_lbl = QLabel(created)
        time_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        top.addWidget(time_lbl)
        cl.addLayout(top)

        # 标题
        title = item.get("title", "")[:40] or "无标题"
        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {TEXT_PRIMARY};")
        cl.addWidget(title_lbl)

        # 内容预览
        content = (item.get("content") or "")[:60].replace("\n", " ")
        content_lbl = QLabel(content + ("..." if len(item.get("content") or "") > 60 else ""))
        content_lbl.setWordWrap(True)
        content_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        cl.addWidget(content_lbl)

        cl.addStretch()

        # 操作按钮
        btn_row = QHBoxLayout()
        view_btn = PushButton("查看")
        view_btn.setFixedHeight(28)
        view_btn.setMinimumWidth(60)
        view_btn.clicked.connect(lambda _, iid=item["id"]: self._on_view_item(iid))
        btn_row.addWidget(view_btn)

        edit_btn = PushButton("编辑")
        edit_btn.setFixedHeight(28)
        edit_btn.setMinimumWidth(60)
        edit_btn.clicked.connect(lambda _, iid=item["id"]: self._on_edit_item(iid))
        btn_row.addWidget(edit_btn)

        if status != "published":
            pub_btn = PrimaryPushButton("发布")
            pub_btn.setFixedHeight(28)
            pub_btn.setMinimumWidth(60)
            pub_btn.clicked.connect(lambda _, iid=item["id"]: self._on_publish_item(iid))
            btn_row.addWidget(pub_btn)

        btn_row.addStretch()
        cl.addLayout(btn_row)

        return card

    def _load_table(self):
        """渲染表格视图"""
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            cb = CheckBox()
            cb.stateChanged.connect(lambda s, iid=item["id"]: self._on_item_checked(iid, s))
            self._card_checkboxes[item["id"]] = cb
            self.table.setCellWidget(row, 0, cb)

            title = item.get("title", "")[:40] or "无标题"
            self.table.setItem(row, 1, self._make_item(title))

            product = item.get("product_name", "")[:20]
            self.table.setItem(row, 2, self._make_item(product))

            status = item.get("status", "draft")
            status_item = self._make_item(status)
            color = SUCCESS if status == "published" else (PRIMARY if status == "draft" else ERROR)
            status_item.setForeground(QColor(color))
            self.table.setItem(row, 3, status_item)

            created = item.get("created_at", "")[:10] if item.get("created_at") else ""
            self.table.setItem(row, 4, self._make_item(created))

            # 操作按钮
            action_widget = QWidget()
            al = QHBoxLayout(action_widget)
            al.setContentsMargins(4, 2, 4, 2)
            al.setSpacing(6)
            view_btn = PushButton("查看")
            view_btn.setFixedHeight(26)
            view_btn.clicked.connect(lambda _, iid=item["id"]: self._on_view_item(iid))
            al.addWidget(view_btn)
            edit_btn = PushButton("编辑")
            edit_btn.setFixedHeight(26)
            edit_btn.clicked.connect(lambda _, iid=item["id"]: self._on_edit_item(iid))
            al.addWidget(edit_btn)
            self.table.setCellWidget(row, 5, action_widget)

    def _make_item(self, text: str) -> QTableWidgetItem:
        from PyQt5.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        return item

    def _on_item_checked(self, item_id: int, state: int):
        if state == Qt.Checked:
            self._selected_ids.add(item_id)
        else:
            self._selected_ids.discard(item_id)
        self.selected_label.setText(f"已选 {len(self._selected_ids)} 条")

    def _on_select_all(self, state: int):
        checked = state == Qt.Checked
        for cb in self._card_checkboxes.values():
            cb.setChecked(checked)

    def _on_view_item(self, item_id: int):
        item = next((i for i in self._items if i["id"] == item_id), None)
        if not item:
            return
        dialog = HistoryDetailDialog(item, self)
        dialog.exec_()

    def _on_edit_item(self, item_id: int):
        item = next((i for i in self._items if i["id"] == item_id), None)
        if item:
            self.history_selected.emit(item)

    def _on_publish_item(self, item_id: int):
        item = next((i for i in self._items if i["id"] == item_id), None)
        if item:
            self.publish_requested.emit(item)

    def _on_delete_selected(self):
        if not self._selected_ids:
            InfoBar.warning("提示", "请先选择要删除的记录", parent=self)
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除选中的 {len(self._selected_ids)} 条记录吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            from src.database.db_manager import get_db_manager
            from src.database.models import GeneratedNote

            db = get_db_manager()
            with db.get_session() as session:
                for item_id in list(self._selected_ids):
                    note = session.query(GeneratedNote).filter_by(id=item_id).first()
                    if note:
                        session.delete(note)
                session.commit()
            InfoBar.success("删除成功", f"已删除 {len(self._selected_ids)} 条记录", parent=self)
            self._selected_ids.clear()
            self._load_history()
        except Exception as e:
            logger.error("Delete history failed: %s", e)
            InfoBar.error("删除失败", str(e), parent=self)


class HistoryDetailDialog(QDialog):
    """生成历史详情弹窗"""

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成详情")
        self.setMinimumSize(680, 520)
        self._item = item
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # 标题
        title = QLabel(self._item.get("title", "") or "无标题")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        # 元信息
        meta = QLabel(
            f"产品：{self._item.get('product_name', '')}  |  "
            f"状态：{self._item.get('status', '')}  |  "
            f"创建时间：{self._item.get('created_at', '')[:19] if self._item.get('created_at') else ''}"
        )
        meta.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(meta)

        # 正文
        layout.addWidget(QLabel("正文内容："))
        content_edit = QPlainTextEdit()
        content_edit.setPlainText(self._item.get("content") or "")
        content_edit.setReadOnly(True)
        content_edit.setMaximumHeight(200)
        layout.addWidget(content_edit)

        # 标签
        tags = self._item.get("tags", "") or ""
        if tags:
            layout.addWidget(QLabel("标签："))
            tags_lbl = QLabel(tags)
            tags_lbl.setStyleSheet(f"color: {PRIMARY}; font-size: 13px;")
            tags_lbl.setWordWrap(True)
            layout.addWidget(tags_lbl)

        # 图片
        images = self._item.get("images") or []
        if images:
            layout.addWidget(QLabel(f"图片（{len(images)} 张）："))
            img_row = QHBoxLayout()
            for img_path in images[:6]:
                if os.path.exists(img_path):
                    lbl = QLabel()
                    pm = QPixmap(img_path).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    lbl.setPixmap(pm)
                    img_row.addWidget(lbl)
            img_row.addStretch()
            layout.addLayout(img_row)

        layout.addStretch()

        # 关闭按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = PushButton("关闭")
        close_btn.setFixedHeight(36)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
