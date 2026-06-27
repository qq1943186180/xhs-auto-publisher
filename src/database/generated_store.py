"""
持久化存储 - AI生成内容 + 发布状态
内部实现为 SQLite（通过 GeneratedNote ORM），保持公共 API 不变。
"""
import logging
import json
from datetime import datetime
from pathlib import Path

from src.paths import DATA_DIR

logger = logging.getLogger(__name__)

_legacy_migration_checked = False


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _normalize_images(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value]
    return []


def _legacy_records(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("notes", "items", "data", "records"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
    return []


def _migrate_legacy_json_if_needed(db):
    """Import old generated_notes.json once when the SQLite store is empty."""
    global _legacy_migration_checked
    if _legacy_migration_checked:
        return
    _legacy_migration_checked = True

    legacy_path = DATA_DIR / "generated_notes.json"
    if not legacy_path.exists():
        return

    from src.database.models import GeneratedNote

    try:
        with db.get_session() as session:
            if session.query(GeneratedNote).count() > 0:
                return

            raw = json.loads(Path(legacy_path).read_text(encoding="utf-8"))
            records = [item for item in _legacy_records(raw) if isinstance(item, dict)]
            if not records:
                return

            for item in records:
                session.add(GeneratedNote(
                    product_name=item.get("product_name", "") or item.get("product", "") or "",
                    title=item.get("title") or item.get("name") or "Untitled",
                    content=item.get("content", "") or "",
                    tags=item.get("tags", "") or "",
                    images=_normalize_images(item.get("images") or item.get("image_paths")),
                    status=item.get("status", "draft") or "draft",
                    direction_id=item.get("direction_id", "") or "",
                    direction_name=item.get("direction_name", "") or "",
                    variants=item.get("variants") or [],
                    selected_variant_index=int(item.get("selected_variant_index") or 0),
                    published_at=_parse_datetime(item.get("published_at")),
                    error=item.get("error"),
                    created_at=_parse_datetime(item.get("created_at")) or datetime.now(),
                ))
            logger.info("Migrated %d legacy generated notes from %s", len(records), legacy_path)
    except Exception as exc:
        logger.warning("Legacy generated_notes.json migration skipped: %s", exc)


def _get_session():
    """获取数据库会话"""
    from src.database.db_manager import get_db_manager
    db = get_db_manager()
    db.create_tables()
    _migrate_legacy_json_if_needed(db)
    return db.get_session()


def _note_to_dict(note) -> dict:
    """ORM 对象转字典（保持旧 JSON 格式兼容）"""
    return {
        "id": note.id,
        "product_name": note.product_name or "",
        "title": note.title,
        "content": note.content or "",
        "tags": note.tags or "",
        "images": note.images or [],
        "status": note.status or "draft",
        "direction_id": note.direction_id or "",
        "direction_name": note.direction_name or "",
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "published_at": note.published_at.isoformat() if note.published_at else None,
        "error": note.error,
        "failure_reason": getattr(note, "failure_reason", None),
        "retry_count": getattr(note, "retry_count", 0) or 0,
        "last_failed_at": note.last_failed_at.isoformat() if getattr(note, "last_failed_at", None) else None,
        "variants": note.variants or [],
        "selected_variant_index": note.selected_variant_index or 0,
    }


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
    from src.database.models import GeneratedNote

    with _get_session() as session:
        note = GeneratedNote(
            product_name=product_name or "",
            title=title,
            content=content or "",
            tags=tags or "",
            images=images or [],
            status=status,
            direction_id=direction_id or "",
            direction_name=direction_name or "",
            variants=variants or [],
            selected_variant_index=selected_variant_index or 0,
        )
        session.add(note)
        session.flush()
        result = _note_to_dict(note)
        logger.info("Saved note: %s (id=%s, dir=%s)", title[:30], note['id'] if isinstance(note, dict) else note.id, direction_name)
        return result


def update_note_status(note_id: int, status: str, error: str = None):
    """Update note publish status"""
    from src.database.models import GeneratedNote

    with _get_session() as session:
        note = session.query(GeneratedNote).filter_by(id=note_id).first()
        if note:
            note.status = status
            if status == "published":
                note.published_at = datetime.now()
            if error:
                note.error = error
            if status == "failed":
                note.failure_reason = error or "未知错误"
                note.last_failed_at = datetime.now()
                note.retry_count = (note.retry_count or 0) + 1


def update_note_images(note_id: int, images: list):
    """Update note image paths"""
    from src.database.models import GeneratedNote

    with _get_session() as session:
        note = session.query(GeneratedNote).filter_by(id=note_id).first()
        if note:
            note.images = images or []


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
    from src.database.models import GeneratedNote

    with _get_session() as session:
        note = session.query(GeneratedNote).filter_by(id=note_id).first()
        if not note:
            return
        if title is not None:
            note.title = title
        if content is not None:
            note.content = content
        if tags is not None:
            note.tags = tags
        if images is not None:
            note.images = images or []
        if product_name is not None:
            note.product_name = product_name
        if status is not None:
            note.status = status
            if status == "published":
                note.published_at = datetime.now()
        if direction_id is not None:
            note.direction_id = direction_id
        if direction_name is not None:
            note.direction_name = direction_name
        if variants is not None:
            note.variants = variants or []
        if selected_variant_index is not None:
            note.selected_variant_index = selected_variant_index
        if error is not None:
            note.error = error


def get_all_notes() -> list:
    """Get all saved notes"""
    from src.database.models import GeneratedNote

    with _get_session() as session:
        notes = session.query(GeneratedNote).order_by(GeneratedNote.id).all()
        return [_note_to_dict(n) for n in notes]


def get_pending_notes() -> list:
    """Get notes waiting to publish"""
    from src.database.models import GeneratedNote

    with _get_session() as session:
        notes = session.query(GeneratedNote).filter(
            GeneratedNote.status.in_(["draft", "pending"])
        ).order_by(GeneratedNote.id).all()
        return [_note_to_dict(n) for n in notes]


def get_failed_notes() -> list:
    """Get notes that failed to publish"""
    from src.database.models import GeneratedNote

    with _get_session() as session:
        notes = session.query(GeneratedNote).filter(
            GeneratedNote.status == "failed"
        ).order_by(GeneratedNote.id).all()
        return [_note_to_dict(n) for n in notes]


def reset_notes_to_pending(note_ids: list) -> int:
    """Batch reset failed notes to pending status for retry. Returns count."""
    from src.database.models import GeneratedNote

    if not note_ids:
        return 0

    with _get_session() as session:
        count = session.query(GeneratedNote).filter(
            GeneratedNote.id.in_(note_ids),
            GeneratedNote.status == "failed",
        ).update({
            GeneratedNote.status: "pending",
            GeneratedNote.failure_reason: None,
            GeneratedNote.error: None,
            GeneratedNote.last_failed_at: None,
        }, synchronize_session="fetch")
    return count


def delete_note(note_id: int):
    """Delete a note"""
    from src.database.models import GeneratedNote

    with _get_session() as session:
        note = session.query(GeneratedNote).filter_by(id=note_id).first()
        if note:
            session.delete(note)


def clear_all():
    """Clear all notes"""
    from src.database.models import GeneratedNote

    with _get_session() as session:
        session.query(GeneratedNote).delete()
