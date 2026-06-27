"""
异步图片加载器 - 基于 QThread 的后台图片加载
先显示占位符，后台加载完成后通过信号更新 QPixmap
注意：后台线程只能用 QImage（线程安全），QPixmap 必须在主线程创建
"""
import os
import logging
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QSize
from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont, QIcon, QImage
from src.utils.logger import get_logger

logger = get_logger("gui.image_loader")

# 占位符缓存，避免重复创建
_PLACEHOLDER_CACHE: dict[str, QPixmap] = {}


def _create_placeholder_pixmap(
    width: int = 200,
    height: int = 260,
    text: str = "加载中...",
    bg_color: str = "#f9fafb",
    text_color: str = "#8a8f98",
) -> QPixmap:
    """创建一个占位符 QPixmap（仅在主线程调用）"""
    cache_key = f"{width}x{height}_{text}"
    if cache_key in _PLACEHOLDER_CACHE:
        return _PLACEHOLDER_CACHE[cache_key]

    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(bg_color))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # 虚线边框
    painter.setPen(QColor("#e5e7eb"))
    painter.drawRect(1, 1, width - 3, height - 3)

    # 居中文字
    painter.setPen(QColor(text_color))
    font = QFont("Microsoft YaHei", 10)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()

    _PLACEHOLDER_CACHE[cache_key] = pixmap
    return pixmap


class _ImageLoadWorker(QThread):
    """后台图片加载线程 — 只用 QImage（线程安全），不碰 QPixmap"""
    image_loaded = pyqtSignal(int, str, QImage)  # index, path, qimage
    load_failed = pyqtSignal(int, str, str)  # index, path, reason

    def __init__(self, index: int, path: str, width: int, height: int, parent=None):
        super().__init__(parent)
        self._index = index
        self._path = path
        self._width = width
        self._height = height

    def run(self):
        try:
            if not os.path.exists(self._path):
                self.load_failed.emit(self._index, self._path, "文件不存在")
                return
            # QImage 是线程安全的，可以在后台加载和缩放
            image = QImage(self._path)
            if image.isNull():
                self.load_failed.emit(self._index, self._path, "图片无法读取")
                return
            scaled = image.scaled(
                self._width, self._height,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.image_loaded.emit(self._index, self._path, scaled)
        except Exception as e:
            logger.warning("Image load failed for %s: %s", self._path, e)
            self.load_failed.emit(self._index, self._path, str(e))


class AsyncImageLoader(QObject):
    """异步图片加载管理器
    先显示占位符，后台加载完成后通过 image_loaded 信号更新
    """
    image_loaded = pyqtSignal(int, str, QPixmap)  # index, path, pixmap
    batch_loaded = pyqtSignal()  # 批量加载完成

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: list[_ImageLoadWorker] = []
        self._pending_count = 0
        self._completed_count = 0

    def load_batch(
        self,
        items: list[dict],
        width: int = 200,
        height: int = 260,
    ):
        """批量加载图片
        items: [{"index": int, "path": str}, ...]
        """
        self._cancel_all()
        self._pending_count = len(items)
        self._completed_count = 0

        for item in items:
            self._load_one(item["index"], item.get("path", ""), width, height)

    def load_single(
        self,
        index: int,
        path: str,
        width: int = 200,
        height: int = 260,
    ):
        """加载单张图片"""
        self._load_one(index, path, width, height)

    def _load_one(self, index: int, path: str, width: int, height: int):
        if not path:
            self._completed_count += 1
            self._emit_batch_loaded_if_done()
            return
        worker = _ImageLoadWorker(index, path, width, height)
        worker.image_loaded.connect(self._on_worker_finished, Qt.QueuedConnection)
        worker.load_failed.connect(self._on_worker_failed, Qt.QueuedConnection)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w), Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater, Qt.QueuedConnection)
        self._workers.append(worker)
        worker.start()

    def _on_worker_finished(self, index: int, path: str, qimage: QImage):
        """主线程回调：将 QImage 转为 QPixmap（GUI 资源必须在主线程）"""
        self._completed_count += 1
        pixmap = QPixmap.fromImage(qimage)
        self.image_loaded.emit(index, path, pixmap)
        self._emit_batch_loaded_if_done()

    def _on_worker_failed(self, index: int, path: str, reason: str):
        self._completed_count += 1
        logger.debug("Image load skipped for %s: %s", path, reason)
        self._emit_batch_loaded_if_done()

    def _cleanup_worker(self, worker: _ImageLoadWorker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    def _emit_batch_loaded_if_done(self):
        if self._completed_count >= self._pending_count:
            self.batch_loaded.emit()

    def _cancel_all(self):
        remaining = []
        for w in list(self._workers):
            if w.isRunning():
                w.quit()
                if not w.wait(1000):
                    logger.debug("Image worker still running, keep reference until finished: %s", getattr(w, "_path", ""))
                    remaining.append(w)
                    continue
            try:
                w.deleteLater()
            except RuntimeError:
                pass
        self._workers = remaining

    def stop(self):
        """Stop outstanding image loading workers before the owner is closed."""
        self._cancel_all()


def async_load_image(
    label,
    path: str,
    width: int = 200,
    height: int = 260,
    placeholder_text: str = "加载中...",
    parent=None,
):
    """便捷函数：异步加载图片到 QLabel
    先设置占位符，后台加载完成后更新
    """
    # 显示占位符
    placeholder = _create_placeholder_pixmap(width, height, placeholder_text)
    label.setPixmap(placeholder)
    label.setAlignment(Qt.AlignCenter)

    if not path or not os.path.exists(path):
        label.setText("无图片" if not path else "文件不存在")
        return

    # 后台加载 — 用 lambda 在主线程做 QImage→QPixmap 转换
    worker = _ImageLoadWorker(0, path, width, height, parent)
    worker.image_loaded.connect(lambda _i, _p, qi: label.setPixmap(QPixmap.fromImage(qi)), Qt.QueuedConnection)
    worker.finished.connect(worker.deleteLater, Qt.QueuedConnection)
    worker.start()
    return worker
