"""
数据库管理模块
- SQLAlchemy ORM
- SQLite 支持
- 自动建表
"""
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from contextlib import contextmanager

# 声明基类
Base = declarative_base()

# 导入所有模型以注册到 Base.metadata
from src.models.product import Product  # noqa: F401
from src.models.task import Task  # noqa: F401
from src.models.publish_history import PublishHistory  # noqa: F401
from src.models.settings import Settings  # noqa: F401


class DatabaseManager:
    """数据库管理器"""

    def __init__(self, db_path: str = None):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径，默认 ~/.xhs-auto-publisher/data.db
        """
        if db_path is None:
            db_dir = Path.home() / ".xhs-auto-publisher"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "data.db")

        self.db_path = db_path
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},
        )

        # 启用 SQLite 外键约束
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def create_tables(self):
        """自动建表"""
        Base.metadata.create_all(self.engine)

    def drop_tables(self):
        """删除所有表（危险操作）"""
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
        """备份数据库"""
        import shutil
        if backup_path is None:
            backup_dir = Path.home() / ".xhs-auto-publisher" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = str(backup_dir / f"data_{timestamp}.db")
        shutil.copy2(self.db_path, backup_path)
        return backup_path

    def init_default_settings(self):
        """初始化默认配置项"""
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


# 全局单例
_db_manager: DatabaseManager = None


def get_db_manager(db_path: str = None) -> DatabaseManager:
    """获取数据库管理器单例"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(db_path)
    return _db_manager
