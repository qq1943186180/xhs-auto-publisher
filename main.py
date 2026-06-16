"""
小红书自动发布系统 - 主程序入口
"""
import sys
import os

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.db_manager import get_db_manager
from src.config.config_manager import get_config_manager
from src.utils.logger import setup_logger, get_logger
from src.gui.main_window import MainWindow, main as gui_main


def main():
    """主程序入口"""
    # 1. 初始化配置
    config = get_config_manager()
    log_config = config.get_section("log")

    # 2. 初始化日志系统
    logger = setup_logger(
        name="xhs-auto-publisher",
        level=log_config.get("level", "INFO"),
        max_file_size_mb=log_config.get("max_file_size_mb", 10),
        backup_count=log_config.get("backup_count", 5),
        console_output=log_config.get("console_output", True),
    )
    logger.info("=" * 50)
    logger.info("小红书自动发布系统启动中...")
    logger.info(f"版本: {config.get('app.version', '1.0.0')}")

    # 3. 初始化数据库
    db_path = config.get("database.path")
    if db_path:
        db_path = os.path.expanduser(db_path)
    db = get_db_manager(db_path)
    db.create_tables()
    db.init_default_settings()
    logger.info("数据库初始化完成")

    # 4. 启动 GUI
    logger.info("正在启动图形界面...")
    gui_main()

    logger.info("程序已退出")


if __name__ == "__main__":
    main()
