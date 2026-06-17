"""
数据库管理模块
- SQLAlchemy ORM
- SQLite 支持
- 自动建表
"""
import threading
import logging
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from src.paths import DATA_DIR
from src.database.base import Base

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库管理器"""

    def __init__(self, db_path: str = None):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径，默认 ~/.xhs-publisher/data.db
        """
        if db_path is None:
            db_dir = DATA_DIR
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "data.db")

        self.db_path = db_path
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},
        )

        # 启用 SQLite 外键约束 + busy_timeout
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def create_tables(self):
        """自动建表"""
        # 导入所有模型以注册到 Base.metadata（延迟导入避免循环依赖）
        import src.models.product  # noqa: F401
        import src.models.task  # noqa: F401
        import src.models.publish_history  # noqa: F401
        import src.models.settings  # noqa: F401
        from src.models.settings import Settings  # noqa: F401
        import src.database.models  # noqa: F401
        Base.metadata.create_all(self.engine)
        self._ensure_existing_schema()

    def _ensure_existing_schema(self):
        """Add newly introduced ORM columns to an existing SQLite database."""
        inspector = inspect(self.engine)
        existing_tables = set(inspector.get_table_names())
        if not existing_tables:
            return

        with self.engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name not in existing_tables:
                    continue
                existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in existing_columns or column.primary_key:
                        continue
                    type_sql = column.type.compile(dialect=self.engine.dialect)
                    table_name = self._quote_identifier(table.name)
                    column_name = self._quote_identifier(column.name)
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {type_sql}"))
                    existing_columns.add(column.name)
                    logger.info("Added missing SQLite column %s.%s", table.name, column.name)

    @staticmethod
    def _quote_identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def drop_tables(self, confirm: bool = False):
        """
        删除所有表（危险操作）

        Args:
            confirm: 必须传 True 才会执行删除
        """
        if not confirm:
            raise RuntimeError(
                "drop_tables() 需要 confirm=True 才会执行，"
                "这会删除所有数据！"
            )
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def get_session(self) -> Session:
        """获取数据库会话（上下文管理器）"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session_factory(self) -> sessionmaker:
        """获取会话工厂"""
        return self.SessionLocal

    def backup(self, backup_path: str = None):
        """
        备份数据库

        优先使用 SQLite 的 .backup API（需要在线备份），
        失败时回退到先 CHECKPOINT 再复制。
        """
        import shutil
        from datetime import datetime

        if backup_path is None:
            backup_dir = DATA_DIR / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = str(backup_dir / f"data_{timestamp}.db")

        # 尝试 SQLite 在线备份
        try:
            import sqlite3
            src_conn = sqlite3.connect(self.db_path)
            dst_conn = sqlite3.connect(backup_path)
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
            return backup_path
        except Exception:
            logger.debug("Handled exception")
            pass

        # 回退：先 WAL checkpoint 再复制
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    __import__("sqlalchemy").text("PRAGMA wal_checkpoint(FULL)")
                )
        except Exception:
            logger.debug("Handled exception")
            pass

        shutil.copy2(self.db_path, backup_path)
        return backup_path

    def init_default_settings(self):
        """初始化默认配置项"""
        from src.models.settings import Settings
        defaults = [
            {"key": "xhs_cookie", "value": "", "value_type": "string", "category": "api", "description": "小红书 Cookie", "is_encrypted": True},
            {"key": "publish_interval", "value": "300", "value_type": "int", "category": "schedule", "description": "发布间隔（秒）"},
            {"key": "max_daily_posts", "value": "10", "value_type": "int", "category": "schedule", "description": "每日最大发布数"},
            {"key": "auto_retry", "value": "true", "value_type": "bool", "category": "general", "description": "失败自动重试"},
            {"key": "notification_enabled", "value": "false", "value_type": "bool", "category": "notification", "description": "启用通知"},
            {"key": "notification_webhook", "value": "", "value_type": "string", "category": "notification", "description": "通知 Webhook 地址"},
        ]
        with self.get_session() as session:
            for setting in defaults:
                existing = session.query(Settings).filter_by(key=setting["key"]).first()
                if not existing:
                    session.add(Settings(**setting))


# 全局单例（线程安全）
_db_manager: DatabaseManager = None
_db_manager_lock = threading.Lock()


def get_db_manager(db_path: str = None) -> DatabaseManager:
    """获取数据库管理器单例（线程安全）"""
    global _db_manager
    if _db_manager is None:
        with _db_manager_lock:
            if _db_manager is None:
                _db_manager = DatabaseManager(db_path)
    return _db_manager
