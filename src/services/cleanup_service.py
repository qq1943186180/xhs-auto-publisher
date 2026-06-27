"""
临时文件清理服务
扫描并清理 ~/.xhs-publisher 下的临时目录和截图。
"""
import logging
import os
import shutil
from pathlib import Path

from src.paths import DATA_DIR

logger = logging.getLogger(__name__)

# 需要清理的目录（相对于 DATA_DIR）
_TEMP_DIRS = [
    "_publish_tmp",
    "_cli_publish_tmp",
    os.path.join("data", "screenshots"),
]

# 项目根目录下可能残留的临时文件模式
_PROJECT_ROOT_PATTERNS = [
    "_test_body.json",
    "debug_*.png",
    "xhs_error_*.png",
]


def _dir_size(path: Path) -> int:
    """递归计算目录大小（字节）"""
    total = 0
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    return total


def scan_temp_files() -> dict:
    """
    扫描所有临时文件/目录，返回统计信息。

    Returns:
        {
            "items": [{"path": str, "size_mb": float, "is_dir": bool}],
            "total_mb": float,
        }
    """
    items: list[dict] = []
    total = 0

    for name in _TEMP_DIRS:
        p = DATA_DIR / name
        if p.exists():
            size = _dir_size(p)
            items.append({
                "path": str(p),
                "size_mb": round(size / (1024 * 1024), 2),
                "is_dir": p.is_dir(),
            })
            total += size

    # 项目根目录残留
    project_root = Path(__file__).resolve().parent.parent.parent
    for pattern in _PROJECT_ROOT_PATTERNS:
        for p in project_root.glob(pattern):
            if p.is_file():
                size = p.stat().st_size
                items.append({
                    "path": str(p),
                    "size_mb": round(size / (1024 * 1024), 2),
                    "is_dir": False,
                })
                total += size

    return {
        "items": items,
        "total_mb": round(total / (1024 * 1024), 2),
    }


def clean_temp_files() -> dict:
    """
    删除所有临时文件/目录。

    Returns:
        {"dirs_cleaned": int, "files_deleted": int, "space_freed_mb": float}
    """
    stats = {"dirs_cleaned": 0, "files_deleted": 0, "space_freed": 0}

    for name in _TEMP_DIRS:
        p = DATA_DIR / name
        if not p.exists():
            continue
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    stats["space_freed"] += f.stat().st_size
                    stats["files_deleted"] += 1
            shutil.rmtree(str(p), ignore_errors=True)
            stats["dirs_cleaned"] += 1
        elif p.is_file():
            stats["space_freed"] += p.stat().st_size
            p.unlink()
            stats["files_deleted"] += 1

    # 项目根目录残留
    project_root = Path(__file__).resolve().parent.parent.parent
    for pattern in _PROJECT_ROOT_PATTERNS:
        for p in project_root.glob(pattern):
            if p.is_file():
                stats["space_freed"] += p.stat().st_size
                p.unlink()
                stats["files_deleted"] += 1

    stats["space_freed_mb"] = round(stats["space_freed"] / (1024 * 1024), 2)
    logger.info(
        "Cleaned %d dirs, %d files, freed %.1f MB",
        stats["dirs_cleaned"], stats["files_deleted"], stats["space_freed_mb"],
    )
    return stats
