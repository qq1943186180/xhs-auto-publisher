"""
千帆后台产品图采集模块

使用 Playwright 浏览器自动化采集小红书千帆后台的商品数据和图片。
"""

from .qianfan_collector import QianfanCollector
from .browser_manager import BrowserManager
from .anti_detect import AntiDetect

__all__ = ["QianfanCollector", "BrowserManager", "AntiDetect"]
