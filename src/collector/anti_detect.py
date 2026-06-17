"""
反爬虫对策模块

提供浏览器指纹伪装、WebDriver 检测规避、随机 User-Agent 等反检测能力。
参考 xhs_ai_publisher 的 fingerprint_service.py，简化为独立工具类。
"""

import random
import time
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict


# ── 常量池 ──────────────────────────────────────────────────────────────────

USER_AGENTS = [
    # Chrome Windows (128-135+)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    # Edge Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
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


# ── 令牌桶限流器 ────────────────────────────────────────────────────────────

class RateLimiter:
    """
    令牌桶限流器

    支持突发流量，令牌按固定速率填充，每次 acquire() 消耗一个令牌。
    无令牌时阻塞等待。

    用法:
        limiter = RateLimiter(rate=1.0, burst=5)  # 每秒 1 个令牌，最多攒 5 个
        await limiter.acquire()  # 阻塞直到有令牌
    """

    def __init__(self, rate: float = 1.0, burst: int = 5):
        """
        Args:
            rate: 每秒产生的令牌数
            burst: 令牌桶最大容量
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """根据时间差补充令牌"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    async def acquire(self) -> None:
        """获取一个令牌，无令牌时阻塞等待"""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # 计算需要等待的时间
                wait_time = (1.0 - self._tokens) / self.rate
            await asyncio.sleep(wait_time)

    @property
    def available(self) -> float:
        """当前可用令牌数（近似值）"""
        self._refill()
        return self._tokens


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

    // 10. 伪造 navigator.connection（网络信息 API）
    if (!navigator.connection) {{
        const fakeConn = {{
            effectiveType: '4g',
            rtt: 50,
            downlink: 10.0,
            saveData: false,
            type: 'wifi',
            downlinkMax: Infinity,
            onchange: null,
            addEventListener: function() {{}},
            removeEventListener: function() {{}},
            dispatchEvent: function() {{ return true; }},
        }};
        Object.defineProperty(navigator, 'connection', {{
            get: () => fakeConn
        }});
    }} else {{
        // 如果已有 connection 对象，补充缺失属性
        try {{
            const conn = navigator.connection;
            if (conn.effectiveType === undefined) conn.effectiveType = '4g';
            if (conn.rtt === undefined) conn.rtt = 50;
            if (conn.downlink === undefined) conn.downlink = 10.0;
            if (conn.saveData === undefined) conn.saveData = false;
        }} catch(e) {{}}
    }}
}})();
"""

    # ── 请求间隔随机化 ─────────────────────────────────────────────────

    @classmethod
    async def human_like_delay(cls, min_sec: float = 0.8, max_sec: float = 3.0):
        """异步等待一段人类般的随机间隔"""
        delay = cls.random_delay(min_sec, max_sec)
        await asyncio.sleep(delay)

    # ── 模拟人类鼠标移动 ───────────────────────────────────────────────

    @staticmethod
    async def human_mouse_move(page, target_x: int, target_y: int, steps: int = 10):
        """模拟人类式鼠标移动轨迹（贝塞尔曲线近似）"""
        # 起点随机化：从页面随机位置出发，不要从 0,0 出发
        start_x = random.randint(100, 800)
        start_y = random.randint(100, 500)

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
        """模拟人类打字速度，包含随机长停顿模拟思考"""
        await page.click(selector)
        i = 0
        while i < len(text):
            char = text[i]
            await page.keyboard.type(char)
            # 随机长停顿：约 15% 概率触发 0.5-2s 停顿（模拟思考）
            if random.random() < 0.15:
                pause = random.uniform(0.5, 2.0)
                await asyncio.sleep(pause)
            else:
                await asyncio.sleep(random.uniform(0.05, 0.15))
            i += 1
