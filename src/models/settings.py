"""
配置数据模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean

from src.database.db_manager import Base


class Settings(Base):
    """系统配置表"""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, comment="配置键")
    value = Column(Text, comment="配置值")
    value_type = Column(String(20), default="string", comment="值类型: string/int/float/bool/json")
    category = Column(String(50), default="general", comment="配置分类: general/api/schedule/notification")
    description = Column(String(500), comment="配置描述")
    is_encrypted = Column(Boolean, default=False, comment="是否加密存储")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def __repr__(self):
        return f"<Settings(key='{self.key}', category='{self.category}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "value_type": self.value_type,
            "category": self.category,
            "description": self.description,
            "is_encrypted": self.is_encrypted,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
