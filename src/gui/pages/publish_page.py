"""
Publish Page - 发布管理
显示所有已生成的笔记，支持发布、删除
"""
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QTableWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QPixmap

from qfluentwidgets import (
    CardWidget, PrimaryPushButton, PushButton, TableWidget,
    ProgressBar, CheckBox, InfoBar
)
from src.gui.styles.theme import (
    BORDER,
    ERROR,
    PRIMARY,
    SUCCESS,
    SURFACE_ALT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    danger_button_style,
    image_tile_style,
    page_subtitle_style,
    page_title_style,
    placeholder_style,
)
from src.gui.utils import PAGE_MARGINS, status_label
from src.gui.widgets.status_badge import StatusBadge
from src.gui.workers.image_loader import AsyncImageLoader, _create_placeholder_pixmap


class PublishPage(QWidget):
    """Publish management page"""

    publish_requested = pyqtSignal(list)
    direct_image_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._image_loader = AsyncImageLoader(self)
        self._image_loader.image_loaded.connect(self._on_batch_image_loaded)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGINS)
        layout.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("发布管理")
        title.setStyleSheet(page_title_style())
        header.addWidget(title)
        subtitle = QLabel("管理待发布笔记、图片和发布状态。")
        subtitle.setStyleSheet(page_subtitle_style())
        header.addWidget(subtitle)
        layout.addLayout(header)

        # Action bar
        card = CardWidget(self)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(12)

        self.count_label = QLabel("共 0 篇笔记")
        self.count_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px;")
        card_layout.addWidget(self.count_label)

        card_layout.addStretch()

        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.clicked.connect(self._on_refresh)
        card_layout.addWidget(self.refresh_btn)

        self.publish_btn = PrimaryPushButton("发布选中")
        self.publish_btn.setFixedHeight(36)
        self.publish_btn.setMinimumWidth(120)
        self.publish_btn.clicked.connect(self._on_publish)
        card_layout.addWidget(self.publish_btn)

        self.publish_all_btn = PrimaryPushButton("全部发布")
        self.publish_all_btn.setFixedHeight(36)
        self.publish_all_btn.setMinimumWidth(120)
        self.publish_all_btn.clicked.connect(self._on_publish_all)
        card_layout.addWidget(self.publish_all_btn)

        self.delete_all_btn = PushButton("全部删除")
        self.delete_all_btn.setFixedHeight(36)
        self.delete_all_btn.setMinimumWidth(100)
        self.delete_all_btn.setStyleSheet(danger_button_style())
        self.delete_all_btn.clicked.connect(self._on_delete_all)
        card_layout.addWidget(self.delete_all_btn)

        layout.addWidget(card)

        # Progress
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Table
        self.table = TableWidget(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["", "产品", "标题", "图片", "状态", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 100)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table)

    def _build_item_from_note(self, n: dict) -> dict:
        """统一构建 item 数据，消除重复代码"""
        raw_status = n.get("status", "draft")
        display_status = status_label(raw_status)
        return {
            "id": n.get("id"),
            "title": n.get("title", ""),
            "content": n.get("content", ""),
            "tags": n.get("tags", ""),
            "images": n.get("images", []),
            "image_count": f"{len(n.get('images', []))}张",
            "status": display_status,
            "raw_status": raw_status,
            "product_name": n.get("product_name", ""),
            "created_at": n.get("created_at", ""),
            "published_at": n.get("published_at", ""),
            "error": n.get("error", ""),
            "variants": n.get("variants", []),
            "selected_variant_index": n.get("selected_variant_index", 0),
        }

    def load_items(self, items: list):
        """Load items into table with diff logic: only update changed rows"""
        old_items = self._items
        self._items = items
        self.count_label.setText(f"共 {len(items)} 篇笔记")
        self.delete_all_btn.setEnabled(bool(items))

        # Check if structure changed (different count or different IDs)
        old_ids = [item.get("id") for item in old_items]
        new_ids = [item.get("id") for item in items]
        structure_changed = (
            len(old_ids) != len(new_ids)
            or old_ids != new_ids
        )

        if structure_changed:
            # Full rebuild
            self._rebuild_table(items)
        else:
            # Diff update: only update changed rows
            for row, item in enumerate(items):
                old_item = old_items[row] if row < len(old_items) else {}
                # Check if item content changed
                if (
                    old_item.get("title") != item.get("title")
                    or old_item.get("status") != item.get("status")
                    or old_item.get("image_count") != item.get("image_count")
                    or old_item.get("product_name") != item.get("product_name")
                ):
                    self._update_table_row(row, item)

    def _rebuild_table(self, items: list):
        """Full table rebuild"""
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._populate_table_row(row, item)
        # Load images in background
        self._load_table_images(items)

    def _populate_table_row(self, row: int, item: dict):
        """填充单行表格数据"""
        # Checkbox
        cb = CheckBox()
        self.table.setCellWidget(row, 0, cb)

        # Product name
        product_name = item.get("product_name", "")
        self.table.setItem(row, 1, QTableWidgetItem(product_name[:15]))

        # Title
        self.table.setItem(row, 2, QTableWidgetItem(item.get("title", "")[:30]))

        # Image count / local preview entry
        image_btn = PushButton(self._image_button_text(item))
        image_btn.setFixedSize(92, 30)
        image_btn.setToolTip("查看本地图片和历史路径")
        image_btn.clicked.connect(lambda _, r=row: self._on_images_clicked(r))
        self.table.setCellWidget(row, 3, image_btn)

        # Status with StatusBadge
        status = item.get("status", "草稿")
        raw_status = item.get("raw_status", "draft")
        badge = StatusBadge(raw_status)
        badge.setFixedHeight(28)
        self.table.setCellWidget(row, 4, badge)

        # Actions
        self._populate_action_widget(row, item)

    def _update_table_row(self, row: int, item: dict):
        """更新单行表格数据（不重建）"""
        if row >= self.table.rowCount():
            return

        # Update product name
        product_name = item.get("product_name", "")
        title_item = self.table.item(row, 1)
        if title_item:
            title_item.setText(product_name[:15])

        # Update title
        title_item = self.table.item(row, 2)
        if title_item:
            title_item.setText(item.get("title", "")[:30])

        # Update image count button
        image_btn = self.table.cellWidget(row, 3)
        if isinstance(image_btn, PushButton):
            image_btn.setText(self._image_button_text(item))

        # Update status badge
        raw_status = item.get("raw_status", "draft")
        badge = self.table.cellWidget(row, 4)
        if isinstance(badge, StatusBadge):
            badge.set_status(raw_status)

    def _populate_action_widget(self, row: int, item: dict):
        """填充操作列"""
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        view_btn = PushButton("查看")
        view_btn.setFixedSize(50, 28)
        view_btn.clicked.connect(lambda _, r=row: self._on_view_detail(r))
        action_layout.addWidget(view_btn)

        status = item.get("status", "草稿")
        if status in ("草稿", "待发布", "发布失败"):
            pub_btn = PushButton("发布")
            pub_btn.setFixedSize(50, 28)
            pub_btn.clicked.connect(lambda _, r=row: self._on_publish_single(r))
            action_layout.addWidget(pub_btn)

        del_btn = PushButton("删除")
        del_btn.setFixedSize(50, 28)
        del_btn.clicked.connect(lambda _, r=row: self._on_delete(r))
        action_layout.addWidget(del_btn)

        self.table.setCellWidget(row, 5, action_widget)

    def _on_batch_image_loaded(self, index: int, path: str, pixmap):
        """批量图片加载完成回调（暂不处理，表格图片通过按钮文字显示）"""
        pass

    def _note_images(self, item: dict) -> list:
        images = item.get("images") or []
        return [str(path) for path in images if path]

    def _existing_images(self, item: dict) -> list:
        return [path for path in self._note_images(item) if os.path.exists(path)]

    def _missing_images(self, item: dict) -> list:
        return [path for path in self._note_images(item) if not os.path.exists(path)]

    def _set_item_images(self, item: dict, images: list):
        clean_images = []
        for path in images:
            path = str(path).strip()
            if path and path not in clean_images:
                clean_images.append(path)

        item["images"] = clean_images
        item["image_count"] = f"{len(clean_images)}张"

        note_id = item.get("id")
        if note_id:
            try:
                from src.database.generated_store import update_note_images
                update_note_images(note_id, clean_images)
            except Exception as e:
                InfoBar.error("保存图片失败", str(e), parent=self)
                return

        for existing_item in self._items:
            if existing_item.get("id") == note_id:
                existing_item["images"] = clean_images
                existing_item["image_count"] = f"{len(clean_images)}张"
                break
        self.load_items(self._items)

    def _manual_upload_dir(self, item: dict) -> Path:
        note_id = item.get("id") or "unsaved"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Path.home() / ".xhs-publisher" / "generated_images" / "manual_uploads" / f"note_{note_id}_{stamp}"

    def _copy_local_images(self, item: dict, paths: list) -> list:
        output_dir = self._manual_upload_dir(item)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for source in paths:
            if not source or not os.path.exists(source):
                continue
            suffix = Path(source).suffix.lower() or ".png"
            stem = Path(source).stem[:40] or "image"
            dest = output_dir / f"{stem}{suffix}"
            counter = 1
            while dest.exists():
                dest = output_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            shutil.copy2(source, dest)
            copied.append(str(dest))
        return copied

    def _add_local_images(self, item: dict, dialog: QDialog = None):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择本地图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not files:
            return

        copied = self._copy_local_images(item, files)
        if not copied:
            InfoBar.warning("上传失败", "没有可用的图片文件", parent=self)
            return

        images = self._note_images(item) + copied
        self._set_item_images(item, images)
        InfoBar.success("图片已添加", f"已添加 {len(copied)} 张本地图片", parent=self)

        if dialog:
            dialog.accept()
            QTimer.singleShot(0, lambda i=item: self._open_note_detail(i))

    def _remove_image_path(self, item: dict, path: str, dialog: QDialog = None):
        images = [value for value in self._note_images(item) if value != path]
        self._set_item_images(item, images)
        InfoBar.success("图片已移除", "已从这条笔记的图片列表移除", parent=self)
        if dialog:
            dialog.accept()
            QTimer.singleShot(0, lambda i=item: self._open_note_detail(i))

    def _remove_missing_images(self, item: dict, dialog: QDialog = None):
        images = self._existing_images(item)
        self._set_item_images(item, images)
        InfoBar.success("已清理", "缺失的图片路径已移除", parent=self)
        if dialog:
            dialog.accept()
            QTimer.singleShot(0, lambda i=item: self._open_note_detail(i))

    def _build_ai_image_prompt(self, item: dict) -> str:
        product = item.get("product_name") or item.get("title") or "商品"
        title = item.get("title", "")
        content = (item.get("content") or "").replace("\n", " ")
        content = content[:180]

        return (
            "请生成一张适合小红书种草笔记的商品图片。\n"
            f"商品：{product}\n"
            f"笔记标题：{title}\n"
            f"文案语气参考：{content}\n"
            "画面：真实生活方式场景，商品是绝对主体，构图干净，有轻微日常氛围但不要喧宾夺主。\n"
            "构图：竖图 3:4 或 4:5，主体清晰居中，保留适度留白，适合发布为小红书图文首图或配图。\n"
            "光线：柔和自然光或商业棚拍光，质感清楚，边缘干净，阴影自然。\n"
            "风格：真实照片质感，不要过度滤镜，不要卡通，不要海报大字。\n"
            "约束：保持商品形状、颜色、材质和细节真实可信；不要生成水印、二维码、logo、虚构文字、价格牌；不要改变商品身份。"
        )

    def _copy_ai_prompt(self, item: dict):
        QApplication.clipboard().setText(self._build_ai_image_prompt(item))
        InfoBar.success("已复制", "AI 图片提示词已复制，可直接去生图工具使用", parent=self)

    def _open_ai_image_options(self, item: dict, parent_dialog: QDialog = None):
        dialog = QDialog(self)
        dialog.setWindowTitle("AI生成图片")
        dialog.resize(760, 520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("选择 AI 生成方式")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel("自己生成会复制提示词，方便去外部 AI 工具生图；直接生成会由软件调用当前 ChatGPT/Kimi 图片链路，并自动写回这条笔记。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(desc)

        prompt = QPlainTextEdit()
        prompt.setReadOnly(True)
        prompt.setPlainText(self._build_ai_image_prompt(item))
        layout.addWidget(prompt)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self_btn = PushButton("自己生成：复制提示词")
        self_btn.clicked.connect(lambda: self._copy_ai_prompt(item))
        btn_row.addWidget(self_btn)

        direct_btn = PrimaryPushButton("直接生成")
        direct_btn.clicked.connect(lambda: self._request_direct_ai_image(item, dialog, parent_dialog))
        btn_row.addWidget(direct_btn)

        close_btn = PushButton("取消")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
        dialog.exec_()

    def _request_direct_ai_image(self, item: dict, option_dialog: QDialog = None, parent_dialog: QDialog = None):
        if option_dialog:
            option_dialog.accept()
        if parent_dialog:
            parent_dialog.accept()

        payload = dict(item)
        payload["image_prompt"] = self._build_ai_image_prompt(item)
        self.direct_image_requested.emit(payload)
        InfoBar.info("直接生成", "已开始为这条笔记生成图片", duration=4000, parent=self)

    def _image_button_text(self, item: dict) -> str:
        saved_count = len(self._note_images(item))
        existing_count = len(self._existing_images(item))
        missing_count = max(0, saved_count - existing_count)
        if missing_count:
            return f"{existing_count}张/缺{missing_count}"
        return f"{existing_count}张"

    def _on_images_clicked(self, row: int):
        if not 0 <= row < len(self._items):
            return
        item = self._items[row]
        if self._existing_images(item):
            self._open_image_gallery(item)
        else:
            self._open_note_detail(item)

    def _on_view_detail(self, row: int):
        if 0 <= row < len(self._items):
            self._open_note_detail(self._items[row])

    def _open_note_detail(self, item: dict):
        dialog = QDialog(self)
        dialog.setWindowTitle("历史详情")
        dialog.resize(860, 680)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(item.get("title", "") or "未命名笔记")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        meta_parts = [
            f"ID：{item.get('id', '')}",
            f"产品：{item.get('product_name', '')}",
            f"状态：{item.get('status', '')}",
            f"本地图片：{len(self._existing_images(item))}/{len(self._note_images(item))}",
        ]
        variants = item.get("variants") or []
        if variants:
            selected_index = int(item.get("selected_variant_index", 0) or 0) + 1
            meta_parts.append(f"文案版本：第 {selected_index}/{len(variants)} 版")
        if item.get("created_at"):
            meta_parts.append(f"创建：{item.get('created_at')}")
        if item.get("published_at"):
            meta_parts.append(f"发布：{item.get('published_at')}")
        if item.get("error"):
            meta_parts.append(f"错误：{item.get('error')}")
        meta = QLabel("\n".join(meta_parts))
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        meta.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(meta)

        self._add_detail_image_section(layout, item, dialog)

        content = QPlainTextEdit()
        content.setReadOnly(True)
        content.setPlainText(item.get("content", ""))
        content.setMinimumHeight(160)
        layout.addWidget(content)

        tags = QPlainTextEdit()
        tags.setReadOnly(True)
        tags.setPlainText(item.get("tags", ""))
        tags.setMaximumHeight(70)
        layout.addWidget(tags)

        prompt_label = QLabel("AI 图片提示词")
        prompt_label.setStyleSheet(f"font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(prompt_label)

        prompt = QPlainTextEdit()
        prompt.setReadOnly(True)
        prompt.setPlainText(self._build_ai_image_prompt(item))
        prompt.setMaximumHeight(150)
        layout.addWidget(prompt)

        prompt_btn_row = QHBoxLayout()
        prompt_btn_row.addStretch()
        self_prompt_btn = PushButton("自己生成")
        self_prompt_btn.clicked.connect(lambda: self._copy_ai_prompt(item))
        prompt_btn_row.addWidget(self_prompt_btn)

        direct_prompt_btn = PrimaryPushButton("直接生成")
        direct_prompt_btn.clicked.connect(lambda: self._request_direct_ai_image(item, dialog))
        prompt_btn_row.addWidget(direct_prompt_btn)
        layout.addLayout(prompt_btn_row)

        paths = QLabel(self._format_image_paths(item))
        paths.setWordWrap(True)
        paths.setTextInteractionFlags(Qt.TextSelectableByMouse)
        paths.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(paths)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if self._existing_images(item):
            gallery_btn = PushButton("查看图片")
            gallery_btn.clicked.connect(lambda: self._open_image_gallery(item))
            btn_row.addWidget(gallery_btn)

            folder_btn = PushButton("打开文件夹")
            folder_btn.clicked.connect(lambda: self._open_folder(self._existing_images(item)[0]))
            btn_row.addWidget(folder_btn)

        close_btn = PushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.exec_()

    def _add_detail_image_section(self, layout: QVBoxLayout, item: dict, dialog: QDialog):
        header_row = QHBoxLayout()
        image_title = QLabel("图片")
        image_title.setStyleSheet(f"font-weight: bold; color: {TEXT_PRIMARY};")
        header_row.addWidget(image_title)
        header_row.addStretch()

        add_btn = PushButton("本地上传图片")
        add_btn.clicked.connect(lambda: self._add_local_images(item, dialog))
        header_row.addWidget(add_btn)

        ai_btn = PushButton("AI生成图片")
        ai_btn.clicked.connect(lambda: self._open_ai_image_options(item, dialog))
        header_row.addWidget(ai_btn)

        missing = self._missing_images(item)
        if missing:
            clean_btn = PushButton("清理缺失路径")
            clean_btn.clicked.connect(lambda: self._remove_missing_images(item, dialog))
            header_row.addWidget(clean_btn)

        layout.addLayout(header_row)

        images = self._existing_images(item)
        if not images:
            empty = QLabel('这条历史记录还没有可打开的本地图片。可以先复制 AI 提示词去生图，生成后用"本地上传图片"加回来。')
            empty.setWordWrap(True)
            empty.setStyleSheet(placeholder_style() + "QLabel { padding: 14px; }")
            layout.addWidget(empty)
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(210)
        scroll_content = QWidget()
        grid = QGridLayout(scroll_content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        for index, path in enumerate(images):
            tile = self._create_image_tile(path, item=item, dialog=dialog, compact=True)
            grid.addWidget(tile, index // 4, index % 4)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

    def _format_image_paths(self, item: dict) -> str:
        images = self._note_images(item)
        if not images:
            return "图片路径：这条历史记录没有保存图片。"

        lines = ["图片路径："]
        for path in images:
            marker = "存在" if os.path.exists(path) else "缺失"
            lines.append(f"[{marker}] {path}")
        return "\n".join(lines)

    def _open_image_gallery(self, item: dict):
        images = self._existing_images(item)
        if not images:
            InfoBar.warning("没有本地图片", "这条历史记录没有可打开的本地图片", parent=self)
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("本地图片")
        dialog.resize(920, 720)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(item.get("title", "") or item.get("product_name", "") or "本地图片")
        title.setWordWrap(True)
        title.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        summary = QLabel(self._image_button_text(item))
        summary.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        grid = QGridLayout(scroll_content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        for index, path in enumerate(images):
            tile = self._create_image_tile(path, item=item, dialog=dialog)
            grid.addWidget(tile, index // 3, index % 3)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        missing = self._missing_images(item)
        if missing:
            missing_label = QLabel("缺失路径：\n" + "\n".join(missing))
            missing_label.setWordWrap(True)
            missing_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            missing_label.setStyleSheet(f"color: {WARNING};")
            layout.addWidget(missing_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        add_btn = PushButton("本地上传图片")
        add_btn.clicked.connect(lambda: self._add_local_images(item, dialog))
        btn_row.addWidget(add_btn)

        ai_btn = PushButton("AI生成图片")
        ai_btn.clicked.connect(lambda: self._open_ai_image_options(item, dialog))
        btn_row.addWidget(ai_btn)

        if missing:
            clean_btn = PushButton("清理缺失路径")
            clean_btn.clicked.connect(lambda: self._remove_missing_images(item, dialog))
            btn_row.addWidget(clean_btn)

        folder_btn = PushButton("打开文件夹")
        folder_btn.clicked.connect(lambda: self._open_folder(images[0]))
        btn_row.addWidget(folder_btn)

        close_btn = PushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.exec_()

    def _create_image_tile(
        self,
        path: str,
        item: dict = None,
        dialog: QDialog = None,
        compact: bool = False,
    ) -> QWidget:
        tile = QWidget()
        tile.setFixedSize(185, 185) if compact else tile.setFixedSize(260, 260)
        tile.setCursor(Qt.PointingHandCursor)
        tile.setStyleSheet(image_tile_style())
        tile.mousePressEvent = lambda event, p=path: self._open_single_image(p)

        layout = QVBoxLayout(tile)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        # 使用异步加载
        placeholder = _create_placeholder_pixmap(165 if compact else 240, 120 if compact else 185, "加载中...")
        image_label.setPixmap(placeholder)
        self._image_loader.load_single(
            hash(path) % 10000,  # 用 hash 作为临时索引
            path,
            165 if compact else 240,
            120 if compact else 185,
        )
        layout.addWidget(image_label, stretch=1)

        name_label = QLabel(Path(path).name)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
        layout.addWidget(name_label)

        if item is not None:
            remove_btn = PushButton("移除")
            remove_btn.setFixedHeight(26)
            remove_btn.clicked.connect(lambda _, i=item, p=path, d=dialog: self._remove_image_path(i, p, d))
            layout.addWidget(remove_btn)
        return tile

    def _open_single_image(self, path: str):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            InfoBar.warning("无法打开图片", "图片文件无法读取", parent=self)
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(Path(path).name)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(16, 16, 16, 16)
        dialog_layout.setSpacing(12)

        screen = QApplication.primaryScreen().availableGeometry()
        max_width = int(screen.width() * 0.75)
        max_height = int(screen.height() * 0.75)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setPixmap(pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        dialog_layout.addWidget(image_label)

        path_label = QLabel(path)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setStyleSheet(f"color: {TEXT_MUTED};")
        dialog_layout.addWidget(path_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        file_btn = PushButton("打开本地文件")
        file_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        btn_row.addWidget(file_btn)

        folder_btn = PushButton("打开文件夹")
        folder_btn.clicked.connect(lambda: self._open_folder(path))
        btn_row.addWidget(folder_btn)

        close_btn = PushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)
        dialog_layout.addLayout(btn_row)

        dialog.resize(min(max_width + 40, screen.width()), min(max_height + 130, screen.height()))
        dialog.exec_()

    def _open_folder(self, path: str):
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def set_progress(self, current: int, total: int):
        if total > 0:
            self.progress_bar.setValue(int(current / total * 100))
        else:
            self.progress_bar.setValue(0)

    def _load_table_images(self, items: list):
        """后台加载表格中的图片"""
        pass  # 图片通过按钮文字显示，不需要实际加载

    def _on_refresh(self):
        """Reload from store"""
        try:
            from src.database.generated_store import get_all_notes
            notes = get_all_notes()
            items = [self._build_item_from_note(n) for n in notes]
            self.load_items(items)
            InfoBar.success("刷新成功", f"共 {len(items)} 篇笔记", parent=self)
        except Exception as e:
            InfoBar.error("刷新失败", str(e), parent=self)

    def _on_publish(self):
        """Publish selected items"""
        selected = []
        for row in range(self.table.rowCount()):
            cb = self.table.cellWidget(row, 0)
            if isinstance(cb, CheckBox) and cb.isChecked():
                selected.append(self._items[row])
        if selected:
            self.publish_requested.emit(selected)
        else:
            InfoBar.warning("提示", "请先勾选要发布的笔记", parent=self)

    def _on_publish_all(self):
        """Publish all pending items with confirmation"""
        pending = [item for item in self._items if item.get("status") in ("草稿", "待发布", "发布失败")]
        if not pending:
            InfoBar.warning("提示", "没有待发布的笔记", parent=self)
            return

        result = QMessageBox.question(
            self,
            "确认全部发布",
            f"确定发布全部 {len(pending)} 篇笔记吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.publish_requested.emit(pending)

    def _on_publish_single(self, row):
        if 0 <= row < len(self._items):
            self.publish_requested.emit([self._items[row]])

    def _on_delete(self, row):
        if 0 <= row < len(self._items):
            item = self._items[row]
            note_id = item.get("id")
            if note_id:
                try:
                    from src.database.generated_store import delete_note
                    delete_note(note_id)
                except FileNotFoundError as e:
                    logger.warning("Note file not found: %s", e)
                except PermissionError as e:
                    InfoBar.error("删除失败", f"权限不足: {e}", parent=self)
                    return
                except Exception as e:
                    InfoBar.error("删除失败", str(e), parent=self)
                    return
            self._items.pop(row)
            self.load_items(self._items)

    def _on_delete_all(self):
        """Delete all saved note records from publish management."""
        if not self._items:
            InfoBar.warning("提示", "没有可删除的笔记", parent=self)
            return

        count = len(self._items)
        result = QMessageBox.question(
            self,
            "确认全部删除",
            f"确定删除发布管理里的全部 {count} 篇笔记记录吗？\n\n"
            "这只会删除历史记录，不会删除本地图片文件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return

        try:
            from src.database.generated_store import clear_all
            clear_all()
            self._items = []
            self.load_items([])
            InfoBar.success("已删除", f"已删除 {count} 篇笔记记录", parent=self)
        except Exception as e:
            InfoBar.error("删除失败", str(e), parent=self)
