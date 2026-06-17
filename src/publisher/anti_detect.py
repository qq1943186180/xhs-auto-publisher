"""
小红书反检测模块
规避 Playwright/Puppeteer 等自动化工具的检测
"""

import random
import asyncio
import logging
from typing import Optional

from playwright.async_api import BrowserContext, Page

logger = logging.getLogger("xhs.anti_detect")


class AntiDetect:
    """反检测工具类"""

    # 常见的 User-Agent 列表（Chrome 128-135 on Windows/Mac）
    USER_AGENTS = [
        # Chrome 135
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        # Chrome 134
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        # Chrome 133
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        # Chrome 132
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        # Chrome 131
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        # Chrome 130
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        # Chrome 129
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        # Chrome 128
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    ]

    # WebGL 渲染器指纹
    WEBGL_RENDERERS = [
        "ANGLE (NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce RTX 4080 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD Radeon RX 7800 XT Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD Radeon RX 7900 XT Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0)",
    ]

    # WebGL 厂商
    WEBGL_VENDORS = [
        "Google Inc. (NVIDIA)",
        "Google Inc. (Intel)",
        "Google Inc. (AMD)",
    ]

    # 平台字符串
    PLATFORMS = ["Win32", "MacIntel"]

    # 语言列表
    LANGUAGES = [
        ["zh-CN", "zh", "en"],
        ["zh-CN", "zh", "en-US", "en"],
        ["zh-CN", "en"],
    ]

    def __init__(self):
        self._ua = random.choice(self.USER_AGENTS)
        self._webgl_renderer = random.choice(self.WEBGL_RENDERERS)
        self._webgl_vendor = random.choice(self.WEBGL_VENDORS)
        self._platform = random.choice(self.PLATFORMS)
        self._languages = random.choice(self.LANGUAGES)

    def get_launch_args(self) -> list[str]:
        """获取浏览器启动参数"""
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--user-agent={self._ua}",
            "--lang=zh-CN",
            "--window-size=1920,1080",
            f"--window-position={random.randint(0, 200)},{random.randint(0, 100)}",
        ]
        return args

    async def apply_stealth(self, context: BrowserContext) -> None:
        """在 browser context 上注入反检测脚本"""
        stealth_script = self._build_stealth_script()
        await context.add_init_script(stealth_script)
        logger.info("反检测脚本已注入")

    def _build_stealth_script(self) -> str:
        """构建反检测 JavaScript 脚本"""
        languages_str = str(self._languages).replace("'", '"')
        return f"""
        // ===== 1. 移除 WebDriver 标志 =====
        Object.defineProperty(navigator, 'webdriver', {{
            get: () => undefined,
        }});
        delete navigator.__proto__.webdriver;

        // ===== 2. 伪装 navigator 属性 =====
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{self._platform}',
        }});
        Object.defineProperty(navigator, 'languages', {{
            get: () => {languages_str},
        }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: () => {random.choice([4, 8, 12, 16])},
        }});
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: () => {random.choice([4, 8, 16])},
        }});

        // ===== 3. 伪装 plugins =====
        Object.defineProperty(navigator, 'plugins', {{
            get: () => {{
                const plugins = [
                    {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
                    {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' }},
                    {{ name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }},
                ];
                plugins.length = 3;
                return plugins;
            }},
        }});

        // ===== 4. 伪装 WebGL 渲染信息 =====
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {{
            if (parameter === 37445) return '{self._webgl_vendor}';
            if (parameter === 37446) return '{self._webgl_renderer}';
            return getParameter.call(this, parameter);
        }};
        const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {{
            if (parameter === 37445) return '{self._webgl_vendor}';
            if (parameter === 37446) return '{self._webgl_renderer}';
            return getParameter2.call(this, parameter);
        }};

        // ===== 5. 伪装 permissions =====
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({{ state: Notification.permission }})
                : originalQuery(parameters)
        );

        // ===== 6. 隐藏 automation 标志 =====
        Object.defineProperty(window, 'cdc_adoQpoasnfa76pfcZLmcfl_Array', {{ get: () => undefined }});
        Object.defineProperty(window, 'cdc_adoQpoasnfa76pfcZLmcfl_Promise', {{ get: () => undefined }});
        Object.defineProperty(window, 'cdc_adoQpoasnfa76pfcZLmcfl_Symbol', {{ get: () => undefined }});

        // ===== 7. 伪装 chrome 对象 =====
        if (!window.chrome) {{
            window.chrome = {{}};
        }}
        if (!window.chrome.runtime) {{
            window.chrome.runtime = {{}};
        }}

        // ===== 8. 伪装 connection 属性 =====
        if (navigator.connection) {{
            Object.defineProperty(navigator.connection, 'rtt', {{ get: () => {random.randint(50, 150)} }});
        }}

        // ===== 9. 伪装屏幕属性 =====
        Object.defineProperty(screen, 'colorDepth', {{ get: () => 24 }});

        // ===== 10. 防止 toString 检测 =====
        const nativeToString = Function.prototype.toString;
        Function.prototype.toString = function() {{
            if (this === navigator.permissions.query) {{
                return 'function query() {{ [native code] }}';
            }}
            return nativeToString.call(this);
        }};
        """

    async def random_delay(
        self,
        min_ms: int = 500,
        max_ms: int = 2000,
        label: str = ""
    ) -> None:
        """模拟人类随机延迟"""
        delay = random.randint(min_ms, max_ms) / 1000
        if label:
            logger.debug("随机延迟 %s: %.2fs", label, delay)
        await asyncio.sleep(delay)

    async def human_type_delay(self) -> int:
        """模拟人类打字间隔（毫秒）"""
        return random.randint(50, 180)

    async def simulate_mouse_movement(self, page: Page) -> None:
        """模拟随机鼠标移动（从合理起始位置出发，非 (0,0)）"""
        # 从视口中心附近开始，模拟自然的鼠标初始位置
        viewport = page.viewport_size or {"width": 1920, "height": 1080}
        start_x = random.randint(viewport["width"] // 4, viewport["width"] * 3 // 4)
        start_y = random.randint(viewport["height"] // 4, viewport["height"] * 3 // 4)

        # 先移动到起始位置（快速）
        await page.mouse.move(start_x, start_y, steps=3)

        # 然后进行随机移动
        for _ in range(random.randint(2, 5)):
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)
            await page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.1, 0.3))

    async def simulate_scroll(self, page: Page, distance: int = 200) -> None:
        """模拟随机滚动"""
        direction = random.choice([1, -1])
        scroll_amount = distance * direction
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(random.uniform(0.3, 0.8))

    def get_random_viewport(self) -> dict:
        """获取随机视口尺寸"""
        widths = [1366, 1440, 1536, 1920, 1600, 1280]
        heights = [768, 900, 864, 1080, 900, 720]
        idx = random.randint(0, len(widths) - 1)
        return {"width": widths[idx], "height": heights[idx]}

    @property
    def user_agent(self) -> str:
        return self._ua
