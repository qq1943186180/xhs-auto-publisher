"""
备份与恢复服务
将 data.db、config.json、keys.enc、collected/ 打包为 zip，
或从 zip 恢复到 ~/.xhs-publisher/。
"""
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from src.paths import DATA_DIR

logger = logging.getLogger(__name__)

# 需要备份的文件 / 目录（相对于 DATA_DIR）
_BACKUP_ITEMS = [
    "data.db",
    "config.json",
    "keys.enc",
    "collected",
    "generated_images",
]


def create_backup(output_path: str) -> dict:
    """
    创建完整数据备份 zip。

    Returns:
        {"path": str, "size_mb": float, "files": [str]}
    """
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    files_included: list[str] = []

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item_name in _BACKUP_ITEMS:
            item_path = DATA_DIR / item_name
            if not item_path.exists():
                continue

            if item_path.is_file():
                zf.write(str(item_path), item_name)
                files_included.append(item_name)
            elif item_path.is_dir():
                for root, _dirs, filenames in os.walk(item_path):
                    for fn in filenames:
                        full = Path(root) / fn
                        arc = str(full.relative_to(DATA_DIR)).replace("\\", "/")
                        zf.write(str(full), arc)
                        files_included.append(arc)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info("Backup created: %s (%.1f MB, %d files)", output_path, size_mb, len(files_included))
    return {
        "path": output_path,
        "size_mb": round(size_mb, 2),
        "files": files_included,
    }


def restore_backup(backup_path: str) -> dict:
    """
    从 zip 恢复数据到 DATA_DIR。
    恢复前会把当前数据备份到 DATA_DIR/backups/pre_restore_*.zip。
    如果预备份失败，中止恢复（数据安全）。

    Returns:
        {"restored": [str], "pre_backup": str | None}
    """
    backup_path = os.path.abspath(backup_path)
    if not os.path.isfile(backup_path):
        raise FileNotFoundError(f"备份文件不存在: {backup_path}")

    # 先做安全备份 — 失败则中止恢复
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pre_backup_path = str(backup_dir / f"pre_restore_{ts}.zip")
    try:
        create_backup(pre_backup_path)
        logger.info("Pre-restore safety backup: %s", pre_backup_path)
    except Exception as e:
        logger.error("Pre-restore backup failed, aborting restore: %s", e)
        raise RuntimeError(f"预备份失败，已中止恢复以保护数据: {e}") from e

    restored: list[str] = []

    # 解压到临时目录，再逐文件覆盖
    temp_dir = tempfile.mkdtemp(prefix="xhs_restore_", dir=str(DATA_DIR))
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            zf.extractall(temp_dir)

        for item_name in _BACKUP_ITEMS:
            src = Path(temp_dir) / item_name
            dst = DATA_DIR / item_name

            if not src.exists():
                continue

            if src.is_file():
                shutil.copy2(str(src), str(dst))
                restored.append(item_name)
                # 恢复 data.db 后，清理可能过期的 WAL/SHM 日志文件
                if item_name == "data.db":
                    for journal in ("data.db-wal", "data.db-shm"):
                        journal_path = DATA_DIR / journal
                        if journal_path.exists():
                            journal_path.unlink()
                            logger.info("Removed stale journal file: %s", journal_path)
            elif src.is_dir():
                if dst.exists():
                    shutil.rmtree(str(dst), ignore_errors=True)
                shutil.copytree(str(src), str(dst))
                restored.append(item_name)

        logger.info("Restored %d items from %s", len(restored), backup_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return {
        "restored": restored,
        "pre_backup": pre_backup_path,
    }
