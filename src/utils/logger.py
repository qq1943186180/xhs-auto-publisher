"""
日志系统
- 文件和控制台输出
- 不同级别不同颜色
- 日志轮转
"""
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from src.paths import DATA_DIR


# ANSI 颜色码
COLORS = {
    "DEBUG": "\033[36m",     # 青色
    "INFO": "\033[32m",      # 绿色
    "WARNING": "\033[33m",   # 黄色
    "ERROR": "\033[31m",     # 红色
    "CRITICAL": "\033[35m",  # 紫色
    "RESET": "\033[0m",      # 重置
}

# Windows 终端颜色支持
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        # 如果无法启用 ANSI，清空颜色
        COLORS = {k: "" for k in COLORS}


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""

    def __init__(self, fmt=None, datefmt=None, use_colors=True):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors

    def format(self, record):
        # 保存原始 levelname
        original_levelname = record.levelname

        if self.use_colors and record.levelname in COLORS:
            record.levelname = f"{COLORS[record.levelname]}{record.levelname}{COLORS['RESET']}"

        result = super().format(record)
        record.levelname = original_levelname
        return result


def setup_logger(
    name: str = "xhs-auto-publisher",
    level: str = "INFO",
    log_dir: str = None,
    max_file_size_mb: int = 10,
    backup_count: int = 5,
    console_output: bool = True,
) -> logging.Logger:
    """
    初始化日志系统
    
    Args:
        name: 日志器名称
        level: 日志级别
        log_dir: 日志文件目录
        max_file_size_mb: 单个日志文件最大大小（MB）
        backup_count: 保留的备份文件数
        console_output: 是否输出到控制台
    
    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 日志格式
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 控制台输出
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_formatter = ColoredFormatter(log_format, date_format, use_colors=True)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # 文件输出
    if log_dir is None:
        log_dir = DATA_DIR / "logs"
    
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = str(log_dir / f"{name}.log")

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_file_size_mb * 1024 * 1024,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(log_format, date_format)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    logger.info("日志系统初始化完成 | 级别: %s | 文件: %s", level, log_file)
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """获取子日志器"""
    if name:
        return logging.getLogger(f"xhs-auto-publisher.{name}")
    return logging.getLogger("xhs-auto-publisher")
