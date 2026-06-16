"""
发布历史数据模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from src.database.db_manager import Base


class PublishHistory(Base):
    """发布历史表"""
    __tablename__ = "publish_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, comment="关联产品ID")
    task_id = Column(Integer, ForeignKey("tasks.id"), comment="关联任务ID")
    platform = Column(String(50), default="xiaohongshu", comment="发布平台")
    note_id = Column(String(100), comment="笔记ID")
    note_url = Column(String(500), comment="笔记链接")
    title = Column(String(200), comment="发布标题")
    content = Column(Text, comment="发布内容")
    images_count = Column(Integer, default=0, comment="图片数量")
    status = Column(String(20), default="success", comment="状态: success/failed/deleted")
    error_message = Column(Text, comment="错误信息")
    view_count = Column(Integer, default=0, comment="浏览量")
    like_count = Column(Integer, default=0, comment="点赞数")
    comment_count = Column(Integer, default=0, comment="评论数")
    collect_count = Column(Integer, default=0, comment="收藏数")
    extra_data = Column(Text, comment="扩展数据 JSON")
    published_at = Column(DateTime, default=datetime.now, comment="发布时间")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    # 关系
    product = relationship("Product", back_populates="publish_history")
    task = relationship("Task", back_populates="publish_history")

    def __repr__(self):
        return f"<PublishHistory(id={self.id}, note_id='{self.note_id}', status='{self.status}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "task_id": self.task_id,
            "platform": self.platform,
            "note_id": self.note_id,
            "note_url": self.note_url,
            "title": self.title,
            "content": self.content,
            "images_count": self.images_count,
            "status": self.status,
            "error_message": self.error_message,
            "view_count": self.view_count,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "collect_count": self.collect_count,
            "extra_data": self.extra_data,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
