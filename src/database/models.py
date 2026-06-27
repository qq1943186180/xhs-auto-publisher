"""
数据库 ORM 模型 - GeneratedNote
与 db_manager 中的 Base 保持独立导入，避免循环依赖
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON

from src.database.base import Base


class GeneratedNote(Base):
    """AI 生成笔记表（替代原来的 JSON 文件存储）"""
    __tablename__ = "generated_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(200), default="", comment="关联商品名")
    title = Column(String(200), nullable=False, comment="笔记标题")
    content = Column(Text, comment="笔记正文")
    tags = Column(Text, comment="话题标签")
    images = Column(JSON, default=list, comment="图片路径列表")
    status = Column(String(20), default="draft", comment="状态: draft/pending/published/failed")
    direction_id = Column(String(100), default="", comment="方向ID")
    direction_name = Column(String(200), default="", comment="方向名称")
    variants = Column(JSON, default=list, comment="候选变体列表")
    selected_variant_index = Column(Integer, default=0, comment="当前选中的变体索引")
    published_at = Column(DateTime, comment="发布时间")
    error = Column(Text, comment="错误信息")
    failure_reason = Column(Text, comment="失败原因")
    retry_count = Column(Integer, default=0, comment="重试次数")
    last_failed_at = Column(DateTime, comment="最后失败时间")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    def __repr__(self):
        return f"<GeneratedNote(id={self.id}, title='{self.title[:30]}', status='{self.status}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "product_name": self.product_name,
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "images": self.images or [],
            "status": self.status,
            "direction_id": self.direction_id,
            "direction_name": self.direction_name,
            "variants": self.variants or [],
            "selected_variant_index": self.selected_variant_index,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "error": self.error,
            "failure_reason": self.failure_reason,
            "retry_count": self.retry_count or 0,
            "last_failed_at": self.last_failed_at.isoformat() if self.last_failed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
