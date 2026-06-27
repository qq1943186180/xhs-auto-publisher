"""
Workflow State — 持久化发布队列、通知中心、工作流步骤跟踪

纯 Python 模块，不依赖 PyQt5。GUI 层通过信号桥接本模块的状态变化。
所有状态以 JSON 原子写入磁盘（tmp + rename），崩溃后可恢复。
"""
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

from src.paths import DATA_DIR

_QUEUE_FILE = DATA_DIR / "publish_queue.json"
_NOTIFY_FILE = DATA_DIR / "notifications.json"
_MAX_NOTIFICATIONS = 200


# ──────────────────────────────────────────────
# 工作流步骤定义
# ──────────────────────────────────────────────

@dataclass
class StepDef:
    key: str
    label: str
    weight: int = 1  # 权重，用于计算进度百分比


WORKFLOW_STEPS: list = [
    StepDef("direction", "方向生成", weight=2),
    StepDef("content", "文案生成", weight=5),
    StepDef("image", "图片生成", weight=3),
]


# ──────────────────────────────────────────────
# 工具：原子写 JSON
# ──────────────────────────────────────────────

def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically: write to temp file in same dir, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        suffix=".tmp", prefix=".queue_", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        # Windows: cannot rename while target exists
        if path.exists():
            path.unlink()
        os.rename(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = []
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 %s 失败 (%s)，使用默认值", path.name, e)
        return default


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _validate_serializable(data: dict) -> None:
    """Reject bytes or non-JSON-serializable values in queue payload."""
    for key, val in data.items():
        if isinstance(val, bytes):
            raise ValueError(
                f"字段 '{key}' 包含 bytes，请使用媒体文件路径而非二进制数据"
            )


# ══════════════════════════════════════════════
# PublishQueueStore — 持久化发布队列
# ══════════════════════════════════════════════

class PublishQueueStore:
    """
    线程安全的持久化发布队列。

    每条记录结构:
    {
        "id": str,
        "status": "pending" | "publishing" | "published" | "failed",
        "draft": bool,
        "scheduled_at": int | None,  # ms timestamp
        "created_at": int,
        "updated_at": int,
        "error": str | None,
        "note": { ... }  # 笔记数据 (title, content, tags, images, ...)
    }
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _QUEUE_FILE
        self._lock = threading.Lock()
        self._items: list = []
        self._load()

    # ── 内部 ──

    def _load(self) -> None:
        raw = _read_json(self._path, default=[])
        self._items = raw if isinstance(raw, list) else []

    def _save(self) -> None:
        _atomic_write_json(self._path, self._items)

    def _find(self, item_id: str) -> Optional[dict]:
        for item in self._items:
            if item.get("id") == item_id:
                return item
        return None

    # ── 公开 API ──

    def enqueue(
        self,
        note: dict,
        scheduled_at: Optional[int] = None,
        draft: bool = False,
    ) -> str:
        """
        添加发布任务。返回 item_id。

        scheduled_at: 定时发布时间（毫秒时间戳）。
                      如果传入的值看起来像秒（< 10^12），自动转为毫秒。
        """
        _validate_serializable(note)
        if scheduled_at is not None and scheduled_at < 1_000_000_000_000:
            scheduled_at = scheduled_at * 1000  # 秒 → 毫秒

        item_id = _new_id()
        now = _now_ms()
        item = {
            "id": item_id,
            "status": "pending",
            "draft": draft,
            "scheduled_at": scheduled_at,
            "created_at": now,
            "updated_at": now,
            "error": None,
            "note": note,
        }
        with self._lock:
            self._items.append(item)
            self._save()
        return item_id

    def dequeue_next(self) -> Optional[dict]:
        """
        取出下一个待发布且已到期的任务（标记为 publishing）。
        定时任务未到期的不会被取出。
        """
        now = _now_ms()
        with self._lock:
            for item in self._items:
                if item["status"] != "pending":
                    continue
                sched = item.get("scheduled_at")
                if sched and sched > now:
                    continue
                item["status"] = "publishing"
                item["updated_at"] = now
                self._save()
                return dict(item)
        return None

    def mark_done(self, item_id: str) -> None:
        with self._lock:
            item = self._find(item_id)
            if item:
                item["status"] = "published"
                item["updated_at"] = _now_ms()
                item["error"] = None
                self._save()

    def mark_failed(self, item_id: str, error: str) -> None:
        with self._lock:
            item = self._find(item_id)
            if item:
                item["status"] = "failed"
                item["updated_at"] = _now_ms()
                item["error"] = error
                self._save()

    def reset_failed(self, item_id: str) -> None:
        """将失败项重置为 pending，可重新发布。"""
        with self._lock:
            item = self._find(item_id)
            if item and item["status"] == "failed":
                item["status"] = "pending"
                item["updated_at"] = _now_ms()
                item["error"] = None
                self._save()

    def remove(self, item_id: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i["id"] != item_id]
            changed = len(self._items) < before
            if changed:
                self._save()
            return changed

    def clear_done(self) -> int:
        """清除所有已完成的项。返回清除数量。"""
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i["status"] != "published"]
            removed = before - len(self._items)
            if removed:
                self._save()
            return removed

    def get_all(self) -> list:
        with self._lock:
            return [dict(i) for i in self._items]

    def get_pending(self) -> list:
        with self._lock:
            return [dict(i) for i in self._items if i["status"] == "pending"]

    def get_scheduled(self) -> list:
        """获取已到期的定时发布任务。"""
        now = _now_ms()
        with self._lock:
            return [
                dict(i) for i in self._items
                if i["status"] == "pending"
                and i.get("scheduled_at")
                and i["scheduled_at"] <= now
            ]

    def counts(self) -> dict:
        """返回各状态的计数。"""
        result: dict = {}
        with self._lock:
            for item in self._items:
                s = item.get("status", "unknown")
                result[s] = result.get(s, 0) + 1
        return result

    def count_pending(self) -> int:
        return self.counts().get("pending", 0)

    def recover_interrupted(self) -> int:
        """
        将上次崩溃时处于 'publishing' 状态的项恢复为 'pending'。
        返回恢复数量。
        """
        recovered = 0
        with self._lock:
            for item in self._items:
                if item["status"] == "publishing":
                    item["status"] = "pending"
                    item["updated_at"] = _now_ms()
                    recovered += 1
            if recovered:
                self._save()
        if recovered:
            logger.info("恢复了 %d 个中断的发布任务", recovered)
        return recovered


# ══════════════════════════════════════════════
# NotificationCenter — 持久化通知中心
# ══════════════════════════════════════════════

class NotificationCenter:
    """
    持久化通知列表，用于替代消失即忘的 InfoBar。

    每条通知结构:
    {
        "id": str,
        "level": "info" | "warning" | "error" | "success",
        "title": str,
        "message": str,
        "timestamp": int,
        "read": bool,
        "action": dict | None,  # {"page": "publish", "highlight_id": "xxx"}
    }
    """

    def __init__(self, path: Optional[Path] = None, max_items: int = _MAX_NOTIFICATIONS):
        self._path = path or _NOTIFY_FILE
        self._max = max_items
        self._lock = threading.Lock()
        self._items: list = []
        self._listeners: list = []
        self._load()

    def _load(self) -> None:
        raw = _read_json(self._path, default=[])
        self._items = raw if isinstance(raw, list) else []

    def _save(self) -> None:
        _atomic_write_json(self._path, self._items)

    def on_notify(self, callback: Callable) -> None:
        """注册通知回调（新通知时触发）。非 Qt 信号，纯 Python callback。"""
        self._listeners.append(callback)

    def notify(
        self,
        level: str,
        title: str,
        message: str = "",
        action: Optional[dict] = None,
    ) -> str:
        """
        添加一条通知。返回 notification_id。
        GUI 层应通过 on_notify 回调来更新 UI（如弹出 InfoBar）。
        """
        if level not in ("info", "warning", "error", "success"):
            level = "info"

        n = {
            "id": _new_id(),
            "level": level,
            "title": title,
            "message": message,
            "timestamp": _now_ms(),
            "read": False,
            "action": action,
        }

        with self._lock:
            self._items.insert(0, n)
            # Evict old items beyond capacity
            if len(self._items) > self._max:
                self._items = self._items[: self._max]
            self._save()

        # Fire listeners outside lock
        for cb in self._listeners:
            try:
                cb(n)
            except Exception as e:
                logger.debug("通知回调异常: %s", e)

        return n["id"]

    def get_all(self) -> list:
        with self._lock:
            return [dict(i) for i in self._items]

    def get_unread(self) -> list:
        with self._lock:
            return [dict(i) for i in self._items if not i.get("read")]

    def mark_read(self, notification_id: str) -> None:
        with self._lock:
            for n in self._items:
                if n["id"] == notification_id:
                    n["read"] = True
                    break
            self._save()

    def mark_all_read(self) -> None:
        with self._lock:
            for n in self._items:
                n["read"] = True
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._save()

    def count_unread(self) -> int:
        with self._lock:
            return sum(1 for i in self._items if not i.get("read"))

    def counts_by_level(self) -> dict:
        """返回各 level 的未读计数（用于侧边栏徽章）。"""
        result: dict = {}
        with self._lock:
            for n in self._items:
                if not n.get("read"):
                    lv = n.get("level", "info")
                    result[lv] = result.get(lv, 0) + 1
        return result


# ══════════════════════════════════════════════
# WorkflowStepTracker — 生成流水线进度跟踪
# ══════════════════════════════════════════════

class WorkflowStepTracker:
    """
    跟踪一次 AI 生成任务的步骤进度。

    用法:
        tracker = WorkflowStepTracker(total_posts=9, total_images=3)
        tracker.start_step("direction")
        tracker.complete_step("direction")
        tracker.start_step("content")
        tracker.set_sub_progress(3, 9)  # 3/9 篇文案完成
        ...

    GUI 层通过 on_change 回调来更新进度条和步骤指示器。
    """

    def __init__(
        self,
        steps: Optional[list] = None,
        total_posts: int = 9,
        total_images: int = 3,
    ):
        self._steps = steps or WORKFLOW_STEPS
        self._total_weight = sum(s.weight for s in self._steps)
        self._total_posts = total_posts
        self._total_images = total_images

        self._current_step: Optional[str] = None
        self._completed_steps: set = set()
        self._failed_steps: set = set()
        self._sub_current = 0
        self._sub_total = 0
        self._started_at: Optional[int] = None
        self._step_started_at: dict = {}

        self._listeners: list = []
        self._lock = threading.Lock()

    def on_change(self, callback: Callable) -> None:
        """注册状态变化回调。"""
        self._listeners.append(callback)

    def _emit(self) -> None:
        state = self.snapshot()
        for cb in self._listeners:
            try:
                cb(state)
            except Exception as e:
                logger.debug("StepTracker 回调异常: %s", e)

    def start(self) -> None:
        """开始整个工作流。"""
        with self._lock:
            self._started_at = _now_ms()
            self._completed_steps.clear()
            self._failed_steps.clear()
            self._current_step = None
        self._emit()

    def start_step(self, step_key: str) -> None:
        with self._lock:
            self._current_step = step_key
            self._step_started_at[step_key] = _now_ms()
            self._sub_current = 0
            self._sub_total = self._get_sub_total(step_key)
        self._emit()

    def complete_step(self, step_key: str) -> None:
        with self._lock:
            self._completed_steps.add(step_key)
            self._failed_steps.discard(step_key)
            if self._current_step == step_key:
                self._current_step = None
                self._sub_current = self._sub_total
        self._emit()

    def fail_step(self, step_key: str) -> None:
        with self._lock:
            self._failed_steps.add(step_key)
            if self._current_step == step_key:
                self._current_step = None
        self._emit()

    def set_sub_progress(self, current: int, total: Optional[int] = None) -> None:
        """设置当前步骤内的子进度（如 "3/9 篇文案"）。"""
        with self._lock:
            self._sub_current = current
            if total is not None:
                self._sub_total = total
        self._emit()

    def _get_sub_total(self, step_key: str) -> int:
        if step_key == "content":
            return self._total_posts
        if step_key == "image":
            return self._total_images
        return 1

    def snapshot(self) -> dict:
        """返回当前状态的快照。"""
        with self._lock:
            steps_info = []
            accumulated_weight = 0
            for s in self._steps:
                status = "pending"
                if s.key in self._completed_steps:
                    status = "completed"
                    accumulated_weight += s.weight
                elif s.key in self._failed_steps:
                    status = "failed"
                    accumulated_weight += s.weight
                elif s.key == self._current_step:
                    status = "running"

                step_elapsed = None
                if s.key in self._step_started_at:
                    step_elapsed = (_now_ms() - self._step_started_at[s.key]) / 1000

                steps_info.append({
                    "key": s.key,
                    "label": s.label,
                    "status": status,
                    "elapsed_seconds": step_elapsed,
                })

            # 计算总进度百分比
            partial = 0
            if self._current_step and self._sub_total > 0:
                step_def = next(
                    (s for s in self._steps if s.key == self._current_step), None
                )
                if step_def:
                    partial = step_def.weight * (self._sub_current / self._sub_total)
            pct = min(100, int((accumulated_weight + partial) / self._total_weight * 100))

            total_elapsed = None
            if self._started_at:
                total_elapsed = (_now_ms() - self._started_at) / 1000

            return {
                "steps": steps_info,
                "progress_percent": pct,
                "current_step": self._current_step,
                "sub_current": self._sub_current,
                "sub_total": self._sub_total,
                "total_elapsed_seconds": total_elapsed,
                "is_done": len(self._completed_steps) + len(self._failed_steps) >= len(self._steps),
            }

    def reset(self) -> None:
        """重置为初始状态。"""
        with self._lock:
            self._current_step = None
            self._completed_steps.clear()
            self._failed_steps.clear()
            self._sub_current = 0
            self._sub_total = 0
            self._started_at = None
            self._step_started_at.clear()
        self._emit()


# ══════════════════════════════════════════════
# 模块级单例（懒初始化）
# ══════════════════════════════════════════════

_queue_instance: Optional[PublishQueueStore] = None
_notify_instance: Optional[NotificationCenter] = None
_instance_lock = threading.Lock()


def get_publish_queue() -> PublishQueueStore:
    global _queue_instance
    if _queue_instance is None:
        with _instance_lock:
            if _queue_instance is None:
                _queue_instance = PublishQueueStore()
    return _queue_instance


def get_notification_center() -> NotificationCenter:
    global _notify_instance
    if _notify_instance is None:
        with _instance_lock:
            if _notify_instance is None:
                _notify_instance = NotificationCenter()
    return _notify_instance
