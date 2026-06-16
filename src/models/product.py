"""
产品数据模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float
from sqlalchemy.orm import relationship

from src.database.db_manager import Base


class Product(Base):
    """产品表"""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False, comment="产品标题")
    description = Column(Text, comment="产品描述")
    category = Column(String(100), comment="产品分类")
    tags = Column(Text, comment="标签，逗号分隔")
    price = Column(Float, comment="价格")
    images_dir = Column(String(500), comment="图片目录路径")
    video_path = Column(String(500), comment="视频文件路径")
    cover_image = Column(String(500), comment="封面图片路径")
    status = Column(String(20), default="draft", comment="状态: draft/ready/published/archived")
    xhs_note_id = Column(String(100), comment="小红书笔记ID")
    extra_data = Column(Text, comment="扩展数据 JSON")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    # 关系
    tasks = relationship("Task", back_populates="product", cascade="all, delete-orphan")
    publish_history = relationship("PublishHistory", back_populates="product", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Product(id={self.id}, title='{self.title}', status='{self.status}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "price": self.price,
            "images_dir": self.images_dir,
            "video_path": self.video_path,
            "cover_image": self.cover_image,
            "status": self.status,
            "xhs_note_id": self.xhs_note_id,
            "extra_data": self.extra_data,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
