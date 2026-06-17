"""
统一路径常量（向后兼容 — 委托给 src.paths）
"""
from src.paths import DATA_DIR  # noqa: F401

__all__ = ["DATA_DIR"]
