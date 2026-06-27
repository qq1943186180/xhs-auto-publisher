"""
小红书自动发布系统 - 主程序入口
"""
import sys
import os
from pathlib import Path

_FAULT_LOG_HANDLE = None
_SINGLE_INSTANCE_MUTEX = None

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载 .env 文件
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        # dotenv 未安装时手动解析简单的 KEY=VALUE
        for line in _env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from src.database.db_manager import get_db_manager
from src.config.config_manager import get_config_manager
from src.utils.logger import setup_logger, get_logger
from src.utils.kimi_webbridge import ensure_kimi_webbridge
from src.gui.main_window import MainWindow, main as gui_main


def _acquire_single_instance_lock(logger) -> bool:
    """Allow only one desktop instance to run at a time on Windows."""
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform != "win32":
        return True

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        _SINGLE_INSTANCE_MUTEX = kernel32.CreateMutexW(
            None,
            True,
            "Local\\XhsAutoPublisherSingleInstance",
        )
        if not _SINGLE_INSTANCE_MUTEX:
            logger.warning("单实例锁创建失败，继续启动")
            return True

        error_already_exists = 183
        if ctypes.get_last_error() == error_already_exists:
            logger.warning("检测到已有小红书自动发布系统实例在运行，阻止重复启动")
            try:
                from PyQt5.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance() or QApplication(sys.argv)
                QMessageBox.information(
                    None,
                    "小红书自动发布系统已在运行",
                    "已经有一个程序实例在后台运行。\n请先在任务栏或任务管理器中关闭旧窗口，再重新打开。",
                )
                app.quit()
            except Exception:
                pass
            return False
    except Exception as e:
        logger.warning("单实例检查失败，继续启动: %s", e)

    return True


def main():
    """主程序入口"""
    global _FAULT_LOG_HANDLE
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

    # Qt / 浏览器内核这类底层崩溃可能绕过 Python 异常捕获，单独留一份崩溃栈。
    try:
        import faulthandler
        fault_log_path = Path.home() / ".xhs-publisher" / "logs" / "faulthandler.log"
        fault_log_path.parent.mkdir(parents=True, exist_ok=True)
        _FAULT_LOG_HANDLE = open(fault_log_path, "a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_LOG_HANDLE, all_threads=True)
        logger.info("底层崩溃记录已启用 | 文件: %s", fault_log_path)
    except Exception as e:
        logger.warning("底层崩溃记录启用失败: %s", e)

    # 全局异常捕获 — 未处理的异常写入日志文件 + 弹窗通知用户
    import traceback
    def _uncaught_exception_handler(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("未捕获异常导致崩溃:\n%s", msg)
        print(msg, file=sys.stderr)
        # 弹窗通知用户（如果 QApplication 还活着）
        try:
            from PyQt5.QtWidgets import QMessageBox, QApplication
            app = QApplication.instance()
            if app:
                box = QMessageBox()
                box.setIcon(QMessageBox.Critical)
                box.setWindowTitle("程序出错")
                box.setText("发生了未预期的错误，可以点击 Show Details 查看堆栈信息。")
                box.setInformativeText(f"{exc_type.__name__}: {exc_value}")
                box.setDetailedText(msg)
                box.setStandardButtons(QMessageBox.Close)
                box.exec_()
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _uncaught_exception_handler

    # if not _acquire_single_instance_lock(logger):
    #     return
    logger.warning("单实例锁已临时禁用（开发模式）")

    logger.info("=" * 50)
    logger.info("小红书自动发布系统启动中...")
    logger.info(f"版本: {config.get('app.version', '1.0.0')}")

    # 生成图片依赖 Kimi WebBridge。启动时先尽力拉起，避免用户点生图后才发现桥没开。
    kimi_status = ensure_kimi_webbridge(logger=logger)
    if kimi_status.ready:
        logger.info(kimi_status.message)
    else:
        logger.warning(kimi_status.message)

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
