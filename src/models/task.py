"""
任务数据模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from src.database.db_manager import Base


class Task(Base):
    """发布任务表"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, comment="关联产品ID")
    task_type = Column(String(50), nullable=False, comment="任务类型: publish/schedule/batch")
    status = Column(String(20), default="pending", comment="状态: pending/running/success/failed/cancelled")
    scheduled_at = Column(DateTime, comment="计划执行时间")
    started_at = Column(DateTime, comment="实际开始时间")
    finished_at = Column(DateTime, comment="完成时间")
    retry_count = Column(Integer, default=0, comment="已重试次数")
    max_retries = Column(Integer, default=3, comment="最大重试次数")
    error_message = Column(Text, comment="错误信息")
    task_config = Column(Text, comment="任务配置 JSON")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    # 关系
    product = relationship("Product", back_populates="tasks")
    publish_history = relationship("PublishHistory", back_populates="task", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Task(id={self.id}, type='{self.task_type}', status='{self.status}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "task_type": self.task_type,
            "status": self.status,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error_message": self.error_message,
            "task_config": self.task_config,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
