"""
Workflow State 单元测试 (unittest 版)
"""
import json
import logging
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# 确保项目根在 sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.services.workflow_state import (
    PublishQueueStore,
    NotificationCenter,
    WorkflowStepTracker,
    WORKFLOW_STEPS,
    _atomic_write_json,
    _validate_serializable,
)

# 静音该模块的日志
logging.getLogger("src.services.workflow_state").setLevel(logging.CRITICAL)


class _TmpDirMixin:
    """Mixin: 每个测试提供临时目录。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()


def _make_queue(tmp_dir):
    return PublishQueueStore(path=tmp_dir / "queue.json")


def _make_nc(tmp_dir):
    return NotificationCenter(path=tmp_dir / "notifications.json")


# ═══════════════════════════════════════════
# PublishQueueStore 测试
# ═══════════════════════════════════════════


class TestPublishQueueStore(_TmpDirMixin, unittest.TestCase):
    def test_enqueue_and_get_all(self):
        q = _make_queue(self.tmp_dir)
        item_id = q.enqueue({"title": "test", "content": "hello"})
        self.assertTrue(item_id)
        items = q.get_all()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], item_id)
        self.assertEqual(items[0]["status"], "pending")
        self.assertEqual(items[0]["note"]["title"], "test")

    def test_enqueue_rejects_bytes(self):
        q = _make_queue(self.tmp_dir)
        with self.assertRaises(ValueError) as ctx:
            q.enqueue({"title": "ok", "image": b"\x89PNG"})
        self.assertIn("bytes", str(ctx.exception))

    def test_dequeue_next(self):
        q = _make_queue(self.tmp_dir)
        q.enqueue({"title": "first"})
        q.enqueue({"title": "second"})
        item = q.dequeue_next()
        self.assertIsNotNone(item)
        self.assertEqual(item["note"]["title"], "first")
        self.assertEqual(item["status"], "publishing")
        item2 = q.dequeue_next()
        self.assertIsNotNone(item2)
        self.assertEqual(item2["note"]["title"], "second")

    def test_dequeue_returns_none_when_empty(self):
        q = _make_queue(self.tmp_dir)
        self.assertIsNone(q.dequeue_next())

    def test_mark_done(self):
        q = _make_queue(self.tmp_dir)
        item_id = q.enqueue({"title": "done test"})
        q.dequeue_next()
        q.mark_done(item_id)
        items = q.get_all()
        self.assertEqual(items[0]["status"], "published")
        self.assertIsNone(items[0]["error"])

    def test_mark_failed(self):
        q = _make_queue(self.tmp_dir)
        item_id = q.enqueue({"title": "fail test"})
        q.mark_failed(item_id, "network error")
        items = q.get_all()
        self.assertEqual(items[0]["status"], "failed")
        self.assertEqual(items[0]["error"], "network error")

    def test_reset_failed(self):
        q = _make_queue(self.tmp_dir)
        item_id = q.enqueue({"title": "reset test"})
        q.mark_failed(item_id, "some error")
        q.reset_failed(item_id)
        items = q.get_all()
        self.assertEqual(items[0]["status"], "pending")
        self.assertIsNone(items[0]["error"])

    def test_remove(self):
        q = _make_queue(self.tmp_dir)
        item_id = q.enqueue({"title": "remove test"})
        self.assertTrue(q.remove(item_id))
        self.assertEqual(len(q.get_all()), 0)
        self.assertFalse(q.remove("nonexistent"))

    def test_clear_done(self):
        q = _make_queue(self.tmp_dir)
        id1 = q.enqueue({"title": "a"})
        id2 = q.enqueue({"title": "b"})
        q.mark_done(id1)
        removed = q.clear_done()
        self.assertEqual(removed, 1)
        self.assertEqual(len(q.get_all()), 1)
        self.assertEqual(q.get_all()[0]["id"], id2)

    def test_counts(self):
        q = _make_queue(self.tmp_dir)
        id1 = q.enqueue({"title": "a"})
        id2 = q.enqueue({"title": "b"})
        id3 = q.enqueue({"title": "c"})
        q.mark_done(id1)
        q.mark_failed(id2, "err")
        c = q.counts()
        self.assertEqual(c["pending"], 1)
        self.assertEqual(c["published"], 1)
        self.assertEqual(c["failed"], 1)

    def test_count_pending(self):
        q = _make_queue(self.tmp_dir)
        q.enqueue({"title": "a"})
        q.enqueue({"title": "b"})
        self.assertEqual(q.count_pending(), 2)

    def test_scheduled_at_auto_seconds_to_ms(self):
        q = _make_queue(self.tmp_dir)
        q.enqueue({"title": "sched"}, scheduled_at=1)
        items = q.get_all()
        self.assertEqual(items[0]["scheduled_at"], 1000)

    def test_scheduled_item_not_dequeued_before_time(self):
        q = _make_queue(self.tmp_dir)
        future_ms = int(time.time() * 1000) + 60_000
        q.enqueue({"title": "future"}, scheduled_at=future_ms)
        self.assertIsNone(q.dequeue_next())

    def test_scheduled_item_dequeued_when_due(self):
        q = _make_queue(self.tmp_dir)
        past_ms = int(time.time() * 1000) - 1000
        q.enqueue({"title": "due"}, scheduled_at=past_ms)
        item = q.dequeue_next()
        self.assertIsNotNone(item)
        self.assertEqual(item["note"]["title"], "due")

    def test_get_scheduled(self):
        q = _make_queue(self.tmp_dir)
        past = int(time.time() * 1000) - 1000
        future = int(time.time() * 1000) + 60_000
        q.enqueue({"title": "due"}, scheduled_at=past)
        q.enqueue({"title": "future"}, scheduled_at=future)
        q.enqueue({"title": "no_schedule"})
        scheduled = q.get_scheduled()
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]["note"]["title"], "due")

    def test_recover_interrupted(self):
        q = _make_queue(self.tmp_dir)
        q.enqueue({"title": "interrupted"})
        q.dequeue_next()
        self.assertEqual(q.get_all()[0]["status"], "publishing")
        recovered = q.recover_interrupted()
        self.assertEqual(recovered, 1)
        self.assertEqual(q.get_all()[0]["status"], "pending")

    def test_persistence(self):
        path = self.tmp_dir / "persist.json"
        q1 = PublishQueueStore(path=path)
        q1.enqueue({"title": "persistent"})
        q1.enqueue({"title": "also persistent"})

        q2 = PublishQueueStore(path=path)
        self.assertEqual(len(q2.get_all()), 2)
        self.assertEqual(q2.get_all()[0]["note"]["title"], "persistent")

    def test_draft_flag(self):
        q = _make_queue(self.tmp_dir)
        q.enqueue({"title": "draft"}, draft=True)
        items = q.get_all()
        self.assertTrue(items[0]["draft"])


# ═══════════════════════════════════════════
# NotificationCenter 测试
# ═══════════════════════════════════════════


class TestNotificationCenter(_TmpDirMixin, unittest.TestCase):
    def test_notify_and_get_all(self):
        nc = _make_nc(self.tmp_dir)
        nc.notify("info", "Test", "Hello")
        items = nc.get_all()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["level"], "info")
        self.assertEqual(items[0]["title"], "Test")
        self.assertFalse(items[0]["read"])

    def test_unread_count(self):
        nc = _make_nc(self.tmp_dir)
        nc.notify("info", "A")
        nc.notify("warning", "B")
        self.assertEqual(nc.count_unread(), 2)

    def test_mark_read(self):
        nc = _make_nc(self.tmp_dir)
        nid = nc.notify("info", "read me")
        nc.mark_read(nid)
        self.assertEqual(nc.count_unread(), 0)
        self.assertTrue(nc.get_all()[0]["read"])

    def test_mark_all_read(self):
        nc = _make_nc(self.tmp_dir)
        nc.notify("info", "A")
        nc.notify("error", "B")
        nc.mark_all_read()
        self.assertEqual(nc.count_unread(), 0)

    def test_clear(self):
        nc = _make_nc(self.tmp_dir)
        nc.notify("info", "A")
        nc.notify("info", "B")
        nc.clear()
        self.assertEqual(len(nc.get_all()), 0)

    def test_listener_called(self):
        nc = _make_nc(self.tmp_dir)
        listener = MagicMock()
        nc.on_notify(listener)
        nc.notify("success", "Done", "All good")
        listener.assert_called_once()
        call_arg = listener.call_args[0][0]
        self.assertEqual(call_arg["title"], "Done")
        self.assertEqual(call_arg["level"], "success")

    def test_max_capacity_eviction(self):
        nc = NotificationCenter(path=self.tmp_dir / "nc.json", max_items=5)
        for i in range(10):
            nc.notify("info", f"msg {i}")
        self.assertEqual(len(nc.get_all()), 5)
        self.assertEqual(nc.get_all()[0]["title"], "msg 9")

    def test_counts_by_level(self):
        nc = _make_nc(self.tmp_dir)
        nc.notify("info", "A")
        nc.notify("error", "B")
        nc.notify("error", "C")
        nc.notify("warning", "D")
        nc.mark_read(nc.get_all()[-1]["id"])  # mark the oldest (info) as read
        counts = nc.counts_by_level()
        self.assertEqual(counts.get("error"), 2)
        self.assertEqual(counts.get("warning"), 1)
        self.assertEqual(counts.get("info", 0), 0)

    def test_invalid_level_defaults_to_info(self):
        nc = _make_nc(self.tmp_dir)
        nc.notify("bogus", "test")
        self.assertEqual(nc.get_all()[0]["level"], "info")

    def test_persistence(self):
        path = self.tmp_dir / "nc_persist.json"
        n1 = NotificationCenter(path=path)
        n1.notify("warning", "persistent warning")

        n2 = NotificationCenter(path=path)
        self.assertEqual(len(n2.get_all()), 1)
        self.assertEqual(n2.get_all()[0]["title"], "persistent warning")

    def test_action_dict(self):
        nc = _make_nc(self.tmp_dir)
        nc.notify("error", "API fail", action={"page": "settings", "highlight": "api_key"})
        item = nc.get_all()[0]
        self.assertEqual(item["action"]["page"], "settings")

    def test_get_unread(self):
        nc = _make_nc(self.tmp_dir)
        id1 = nc.notify("info", "A")
        nc.notify("info", "B")
        nc.mark_read(id1)
        unread = nc.get_unread()
        self.assertEqual(len(unread), 1)
        self.assertEqual(unread[0]["title"], "B")


# ═══════════════════════════════════════════
# WorkflowStepTracker 测试
# ═══════════════════════════════════════════


class TestWorkflowStepTracker(unittest.TestCase):
    def _make_tracker(self):
        return WorkflowStepTracker(total_posts=9, total_images=3)

    def test_initial_snapshot(self):
        t = self._make_tracker()
        snap = t.snapshot()
        self.assertEqual(snap["progress_percent"], 0)
        self.assertIsNone(snap["current_step"])
        self.assertFalse(snap["is_done"])
        self.assertEqual(len(snap["steps"]), 3)

    def test_start_and_complete_step(self):
        t = self._make_tracker()
        t.start()
        t.start_step("direction")
        snap = t.snapshot()
        self.assertEqual(snap["current_step"], "direction")
        self.assertEqual(snap["steps"][0]["status"], "running")

        t.complete_step("direction")
        snap = t.snapshot()
        self.assertEqual(snap["steps"][0]["status"], "completed")
        self.assertIsNone(snap["current_step"])

    def test_progress_percentage(self):
        t = self._make_tracker()
        t.start()
        t.start_step("direction")
        t.complete_step("direction")
        snap = t.snapshot()
        self.assertEqual(snap["progress_percent"], 20)

        t.start_step("content")
        t.set_sub_progress(4, 9)
        snap = t.snapshot()
        self.assertGreaterEqual(snap["progress_percent"], 40)
        self.assertLessEqual(snap["progress_percent"], 45)

    def test_fail_step(self):
        t = self._make_tracker()
        t.start()
        t.start_step("direction")
        t.fail_step("direction")
        snap = t.snapshot()
        self.assertEqual(snap["steps"][0]["status"], "failed")

    def test_is_done_when_all_steps_terminal(self):
        t = self._make_tracker()
        t.start()
        for step_key in ("direction", "content", "image"):
            t.start_step(step_key)
            t.complete_step(step_key)
        snap = t.snapshot()
        self.assertTrue(snap["is_done"])
        self.assertEqual(snap["progress_percent"], 100)

    def test_on_change_listener(self):
        t = self._make_tracker()
        listener = MagicMock()
        t.on_change(listener)
        t.start()
        self.assertEqual(listener.call_count, 1)
        t.start_step("direction")
        self.assertEqual(listener.call_count, 2)

    def test_reset(self):
        t = self._make_tracker()
        t.start()
        t.start_step("direction")
        t.complete_step("direction")
        t.reset()
        snap = t.snapshot()
        self.assertEqual(snap["progress_percent"], 0)
        self.assertFalse(snap["is_done"])
        self.assertTrue(all(s["status"] == "pending" for s in snap["steps"]))

    def test_elapsed_tracking(self):
        t = self._make_tracker()
        t.start()
        t.start_step("direction")
        time.sleep(0.05)
        snap = t.snapshot()
        self.assertIsNotNone(snap["total_elapsed_seconds"])
        self.assertGreater(snap["total_elapsed_seconds"], 0)
        self.assertIsNotNone(snap["steps"][0]["elapsed_seconds"])

    def test_sub_progress_defaults(self):
        t = self._make_tracker()
        t.start()
        t.start_step("direction")
        snap = t.snapshot()
        self.assertEqual(snap["sub_total"], 1)
        self.assertEqual(snap["sub_current"], 0)


# ═══════════════════════════════════════════
# Atomic write 测试
# ═══════════════════════════════════════════


class TestAtomicWrite(_TmpDirMixin, unittest.TestCase):
    def test_write_and_read(self):
        path = self.tmp_dir / "test.json"
        _atomic_write_json(path, {"key": "value"})
        self.assertTrue(path.exists())
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")

    def test_overwrite_existing(self):
        path = self.tmp_dir / "test.json"
        _atomic_write_json(path, {"a": 1})
        _atomic_write_json(path, {"b": 2})
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertNotIn("a", data)
        self.assertEqual(data["b"], 2)


class TestValidateSerializable(unittest.TestCase):
    def test_rejects_bytes(self):
        with self.assertRaises(ValueError) as ctx:
            _validate_serializable({"file": b"\x00\x01"})
        self.assertIn("bytes", str(ctx.exception))

    def test_accepts_strings(self):
        _validate_serializable({"path": "/tmp/image.png"})  # should not raise


if __name__ == "__main__":
    unittest.main()
