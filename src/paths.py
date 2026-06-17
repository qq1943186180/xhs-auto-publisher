"""
统一路径常量

所有模块应引用这里的 DATA_DIR，不要各自硬编码路径。
"""
from pathlib import Path

DATA_DIR = Path.home() / ".xhs-publisher"
