"""
反爬虫对策模块

提供浏览器指纹伪装、WebDriver 检测规避、随机 User-Agent 等反检测能力。
参考 xhs_ai_publisher 的 fingerprint_service.py，简化为独立工具类。
"""

import random
import json
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict


# ── 常量池 ──────────────────────────────────────────────────────────────────

USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

SCREEN_RESOLUTIONS = [
    (1920, 1080), (1920, 1200), (2560, 1440),
    (1440, 900),  (1536, 864),  (1366, 768),
    (1600, 900),  (1280, 720),
]

TIMEZONES = [
    "Asia/Shanghai", "Asia/Hong_Kong",
    "Asia/Taipei",  "Asia/Singapore",
]

LOCALES = ["zh-CN", "zh"]

PLATFORMS = {
    "Windows": "Win32",
    "Macintosh": "MacIntel",
}

WEBGL_VENDORS = [
    "Google Inc. (Intel)",
    "Google Inc. (NVIDIA)",
    "Google Inc. (AMD)",
]

WEBGL_RENDERERS = [
    "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) HD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
]

COMMON_FONTS = [
    "Arial", "Arial Black", "Bookman", "Comic Sans MS", "Courier New",
    "FangSong", "Garamond", "Georgia", "Impact", "KaiTi",
    "Microsoft YaHei", "Palatino", "SimHei", "SimSun",
    "Times New Roman", "Trebuchet MS", "Verdana",
]


# ── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class BrowserFingerprint:
    """浏览器指纹配置"""
    user_agent: str = ""
    viewport_width: int = 1920
    viewport_height: int = 937
    screen_width: int = 1920
    screen_height: int = 1080
    timezone: str = "Asia/Shanghai"
    locale: str = "zh-CN"
    platform: str = "Win32"
    webgl_vendor: str = "Google Inc. (Intel)"
    webgl_renderer: str = ""
    latitude: float = 31.2304
    longitude: float = 121.4737

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── 核心类 ──────────────────────────────────────────────────────────────────

class AntiDetect:
    """反爬虫对策工具类"""

    # ── 随机 User-Agent ─────────────────────────────────────────────────

    @staticmethod
    def random_user_agent() -> str:
        """返回随机 User-Agent"""
        return random.choice(USER_AGENTS)

    # ── 随机延迟 ────────────────────────────────────────────────────────

    @staticmethod
    def random_delay(min_sec: float = 0.5, max_sec: float = 2.0) -> float:
        """返回随机延迟秒数"""
        return random.uniform(min_sec, max_sec)

    # ── 生成完整指纹 ────────────────────────────────────────────────────

    @classmethod
    def generate_fingerprint(cls) -> BrowserFingerprint:
        """生成一套随机但自洽的浏览器指纹"""
        ua = cls.random_user_agent()
        is_windows = "Windows" in ua
        platform = PLATFORMS["Windows"] if is_windows else PLATFORMS["Macintosh"]

        res = random.choice(SCREEN_RESOLUTIONS)
        # 视口比屏幕小（模拟工具栏/任务栏占用）
        vw = res[0] - random.randint(0, 8)
        vh = res[1] - random.randint(80, 180)

        return BrowserFingerprint(
            user_agent=ua,
            viewport_width=vw,
            viewport_height=vh,
            screen_width=res[0],
            screen_height=res[1],
            timezone=random.choice(TIMEZONES),
            locale=random.choice(LOCALES),
            platform=platform,
            webgl_vendor=random.choice(WEBGL_VENDORS),
            webgl_renderer=random.choice(WEBGL_RENDERERS),
            latitude=round(random.uniform(22.0, 45.0), 6),
            longitude=round(random.uniform(100.0, 130.0), 6),
        )

    # ── Playwright context 参数 ─────────────────────────────────────────

    @classmethod
    def build_context_options(cls, fingerprint: Optional[BrowserFingerprint] = None) -> Dict[str, Any]:
        """根据指纹生成 Playwright BrowserContext 参数"""
        fp = fingerprint or cls.generate_fingerprint()
        return {
            "user_agent": fp.user_agent,
            "viewport": {"width": fp.viewport_width, "height": fp.viewport_height},
            "screen": {"width": fp.screen_width, "height": fp.screen_height},
            "locale": fp.locale,
            "timezone_id": fp.timezone,
            "geolocation": {"latitude": fp.latitude, "longitude": fp.longitude},
            "permissions": ["geolocation"],
            "color_scheme": "light",
        }

    # ── 反检测 JS 注入脚本 ─────────────────────────────────────────────

    @staticmethod
    def stealth_js(fingerprint: Optional[BrowserFingerprint] = None) -> str:
        """生成 Playwright add_init_script 使用的反检测 JS"""
        fp = fingerprint
        ua = fp.user_agent if fp else ""
        platform = fp.platform if fp else "Win32"
        locale = fp.locale if fp else "zh-CN"
        wgl_v = fp.webgl_vendor if fp else random.choice(WEBGL_VENDORS)
        wgl_r = fp.webgl_renderer if fp else random.choice(WEBGL_RENDERERS)

        return f"""
(function() {{
    // 1. 隐藏 webdriver 标志
    Object.defineProperty(navigator, 'webdriver', {{
        get: () => undefined
    }});
    delete navigator.__proto__.webdriver;

    // 2. 伪造 chrome 对象
    if (!window.chrome) {{
        window.chrome = {{}};
    }}
    if (!window.chrome.runtime) {{
        window.chrome.runtime = {{}};
    }}

    // 3. 伪造 plugins（非空，模拟正常浏览器）
    Object.defineProperty(navigator, 'plugins', {{
        get: () => {{
            const p = {{
                0: {{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
                length: 1
            }};
            p[Symbol.iterator] = function*() {{ yield p[0]; }};
            return p;
        }}
    }});

    // 4. 伪造 languages
    Object.defineProperty(navigator, 'languages', {{
        get: () => ['{locale}', 'zh', 'en-US', 'en']
    }});
    Object.defineProperty(navigator, 'language', {{
        get: () => '{locale}'
    }});

    // 5. 伪造 platform
    Object.defineProperty(navigator, 'platform', {{
        get: () => '{platform}'
    }});

    // 6. 伪造 WebGL 渲染信息
    const origGetParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {{
        if (param === 37445) return '{wgl_v}';
        if (param === 37446) return '{wgl_r}';
        return origGetParam.call(this, param);
    }};
    if (typeof WebGL2RenderingContext !== 'undefined') {{
        const origGetParam2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(param) {{
            if (param === 37445) return '{wgl_v}';
            if (param === 37446) return '{wgl_r}';
            return origGetParam2.call(this, param);
        }};
    }}

    // 7. 伪造 permissions query（避免 notifications 被检测为 denied）
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = function(params) {{
        if (params.name === 'notifications') {{
            return Promise.resolve({{ state: Notification.permission }});
        }}
        return origQuery.call(this, params);
    }};

    // 8. 隐藏 Playwright / automation 特征
    Object.defineProperty(navigator, 'maxTouchPoints', {{
        get: () => 0
    }});

    // 9. 防止 iframe contentWindow 检测
    const origAttachShadow = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function() {{
        return origAttachShadow.apply(this, arguments);
    }};
}})();
"""

    # ── 请求间隔随机化 ─────────────────────────────────────────────────

    @classmethod
    async def human_like_delay(cls, min_sec: float = 0.8, max_sec: float = 3.0):
        """异步等待一段人类般的随机间隔"""
        import asyncio
        delay = cls.random_delay(min_sec, max_sec)
        await asyncio.sleep(delay)

    # ── 模拟人类鼠标移动 ───────────────────────────────────────────────

    @staticmethod
    async def human_mouse_move(page, target_x: int, target_y: int, steps: int = 10):
        """模拟人类式鼠标移动轨迹（贝塞尔曲线近似）"""
        import asyncio

        # 获取当前鼠标位置（默认 0,0）
        start_x, start_y = 0, 0

        for i in range(1, steps + 1):
            t = i / steps
            # 简单的三次缓动
            ease = t * t * (3 - 2 * t)
            x = start_x + (target_x - start_x) * ease + random.uniform(-2, 2)
            y = start_y + (target_y - start_y) * ease + random.uniform(-2, 2)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.01, 0.03))

    # ── 模拟人类打字 ───────────────────────────────────────────────────

    @staticmethod
    async def human_type(page, selector: str, text: str):
        """模拟人类打字速度"""
        import asyncio
        await page.click(selector)
        for char in text:
            await page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.05, 0.15))
