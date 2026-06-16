"""
持久化存储 - AI生成内容 + 发布状态
JSON文件存储，支持增删改查
"""
import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STORE_DIR = Path.home() / ".xhs-publisher"
STORE_FILE = STORE_DIR / "generated_notes.json"


def _ensure_dir():
    STORE_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> list:
    """Load all saved notes"""
    if not STORE_FILE.exists():
        return []
    try:
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Load store failed: {e}")
        return []


def _save(notes: list):
    """Save notes to file"""
    _ensure_dir()
    try:
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save store failed: {e}")


def save_note(
    title: str,
    content: str,
    tags: str = "",
    images: list = None,
    product_name: str = "",
    status: str = "draft",  # draft / pending / published / failed
    direction_id: str = "",
    direction_name: str = "",
    variants: list = None,
    selected_variant_index: int = 0,
) -> dict:
    """Save a generated note"""
    notes = _load()
    next_id = max([int(n.get("id", 0) or 0) for n in notes] + [0]) + 1

    note = {
        "id": next_id,
        "product_name": product_name,
        "title": title,
        "content": content,
        "tags": tags,
        "images": images or [],
        "status": status,
        "direction_id": direction_id,
        "direction_name": direction_name,
        "created_at": datetime.now().isoformat(),
        "published_at": None,
        "error": None,
    }
    if variants is not None:
        note["variants"] = variants or []
        note["selected_variant_index"] = selected_variant_index or 0
    notes.append(note)
    _save(notes)
    logger.info(f"Saved note: {title[:30]} (id={note['id']}, dir={direction_name})")
    return note


def update_note_status(note_id: int, status: str, error: str = None):
    """Update note publish status"""
    notes = _load()
    for note in notes:
        if note.get("id") == note_id:
            note["status"] = status
            if status == "published":
                note["published_at"] = datetime.now().isoformat()
            if error:
                note["error"] = error
            break
    _save(notes)


def update_note_images(note_id: int, images: list):
    """Update note image paths"""
    notes = _load()
    for note in notes:
        if note.get("id") == note_id:
            note["images"] = images or []
            break
    _save(notes)


def update_note(
    note_id: int,
    title: str = None,
    content: str = None,
    tags: str = None,
    images: list = None,
    product_name: str = None,
    status: str = None,
    direction_id: str = None,
    direction_name: str = None,
    variants: list = None,
    selected_variant_index: int = None,
    error: str = None,
):
    """Update saved note fields without creating a duplicate record."""
    notes = _load()
    for note in notes:
        if note.get("id") == note_id:
            if title is not None:
                note["title"] = title
            if content is not None:
                note["content"] = content
            if tags is not None:
                note["tags"] = tags
            if images is not None:
                note["images"] = images or []
            if product_name is not None:
                note["product_name"] = product_name
            if status is not None:
                note["status"] = status
                if status == "published":
                    note["published_at"] = datetime.now().isoformat()
            if direction_id is not None:
                note["direction_id"] = direction_id
            if direction_name is not None:
                note["direction_name"] = direction_name
            if variants is not None:
                note["variants"] = variants or []
            if selected_variant_index is not None:
                note["selected_variant_index"] = selected_variant_index
            if error is not None:
                note["error"] = error
            break
    _save(notes)


def get_all_notes() -> list:
    """Get all saved notes"""
    return _load()


def get_pending_notes() -> list:
    """Get notes waiting to publish"""
    return [n for n in _load() if n.get("status") in ("draft", "pending")]


def delete_note(note_id: int):
    """Delete a note"""
    notes = _load()
    notes = [n for n in notes if n.get("id") != note_id]
    _save(notes)


def clear_all():
    """Clear all notes"""
    _save([])
