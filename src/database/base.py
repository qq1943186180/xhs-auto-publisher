"""SQLAlchemy 声明基类 — 独立文件避免循环导入"""
from sqlalchemy.orm import declarative_base

Base = declarative_base()
