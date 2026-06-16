"""
小红书自动发布示例
"""

import asyncio
import logging
from pathlib import Path

# 设置项目根路径，以便 import
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from publisher import XhsPublisher
from publisher.xhs_publisher import NoteData

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


async def example_single_publish():
    """示例：发布单条笔记"""
    note = NoteData(
        title="今日穿搭分享",
        content="今天天气真好，出门逛街穿了这件衣服～\n面料很舒服，推荐给大家！\n\n#穿搭 #日常分享",
        images=[
            "./images/outfit1.jpg",
            "./images/outfit2.jpg",
            "./images/outfit3.jpg",
        ],
        topics=["穿搭", "日常分享"],
    )

    async with XhsPublisher(headless=False) as publisher:
        # 登录（首次使用需要扫码）
        if not await publisher.login(timeout=300):
            print("登录失败，退出")
            return

        # 发布
        result = await publisher.publish_note(note)
        print(f"发布结果: {'✅ 成功' if result.success else '❌ 失败'} - {result.message}")


async def example_batch_publish():
    """示例：批量发布多条笔记"""
    notes = [
        NoteData(
            title="好物推荐｜这款面霜真的绝了",
            content="用了两周，皮肤明显变好了...",
            images=["./images/product1.jpg"],
            topics=["好物推荐", "护肤"],
        ),
        NoteData(
            title="周末brunch打卡",
            content="发现一家超好吃的brunch店...",
            images=["./images/food1.jpg", "./images/food2.jpg"],
            topics=["美食探店", "brunch"],
        ),
    ]

    async with XhsPublisher(headless=False) as publisher:
        if not await publisher.login(timeout=300):
            print("登录失败，退出")
            return

        # 批量发布，每条间隔 60-180 秒
        results = await publisher.batch_publish(
            notes,
            interval_min=60,
            interval_max=180,
        )

        for r in results:
            status = "✅" if r.success else "❌"
            print(f"  {status} {r.note_title}: {r.message}")


async def example_scheduled_publish():
    """示例：定时发布"""
    from datetime import datetime, timedelta

    notes = [
        NoteData(
            title="早安问候",
            content="新的一天开始了，加油！",
            images=["./images/morning.jpg"],
            topics=["早安"],
            scheduled_time=datetime.now() + timedelta(minutes=5),
        ),
    ]

    async with XhsPublisher(headless=False) as publisher:
        if not await publisher.login(timeout=300):
            return
        results = await publisher.batch_publish(notes, scheduled=True)
        for r in results:
            print(f"{'✅' if r.success else '❌'} {r.note_title}")


if __name__ == "__main__":
    asyncio.run(example_single_publish())
