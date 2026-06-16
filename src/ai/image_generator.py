"""
小红书主图生成器 - Kimi WebBridge + ChatGPT DALL-E
用浏览器自动化调 ChatGPT 生图，不需要 OpenAI API Key
3种风格变体：博主风/纯白简约/氛围场景
"""
import io
import os
import json
import base64
import time
import logging
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .prompt_templates import get_all_image_prompts

logger = logging.getLogger(__name__)

# ========== 常量 ==========
KIMI_URL = "http://127.0.0.1:10086/command"
SESSION = "xhs-img-gen"
POLL_SHORT = 1
POLL_MEDIUM = 3
POLL_LONG = 5
IMG_SIZE_THRESHOLD = 1000
IMG_BODY_MIN_LEN = 1000
FETCH_MAX_RETRY = 3
SEND_MAX_RETRY = 2
PREVIEW_MAX_WAIT = 15
PAGE_READY_TIMEOUT = 30
IMAGE_GEN_TIMEOUT = 120
UPLOAD_TIMEOUT = 30
DETAIL_TIMEOUT = 60
MAX_IMG_SIZE_MB = 10
MAX_PARALLEL_WORKERS = 3


# ========== Kimi API ==========

class KimiError(Exception):
    pass


def kimi(action, args=None, session=SESSION, timeout=UPLOAD_TIMEOUT):
    payload = {"action": action, "args": args or {}, "session": session}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(KIMI_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise KimiError(f"{action} 失败: {e}")


def kimi_safe(action, args=None, session=SESSION, timeout=UPLOAD_TIMEOUT):
    try:
        return kimi(action, args, session, timeout)
    except KimiError as e:
        logger.warning(str(e))
        return {}


def poll_until(predicate, timeout, interval=POLL_SHORT, label=""):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    return None


# ========== 页面操作 ==========

def wait_for_page_ready(timeout=PAGE_READY_TIMEOUT, session=SESSION):
    def check():
        r = kimi_safe("evaluate", {'code': '!!document.querySelector("div.ProseMirror")'}, session=session)
        return r.get("data", {}).get("value")
    return poll_until(check, timeout, POLL_SHORT, "页面加载")


def wait_for_send_button(timeout=PREVIEW_MAX_WAIT, session=SESSION):
    def check():
        r = kimi_safe("evaluate", {
            'code': 'document.querySelector(\'button[data-testid="send-button"]\')?.getAttribute("aria-label")'
        }, session=session)
        label = str(r.get("data", {}).get("value", ""))
        return "发送" in label
    return poll_until(check, timeout, POLL_SHORT, "发送按钮")


def wait_for_image(timeout=IMAGE_GEN_TIMEOUT, session=SESSION):
    """轮询检测 DALL-E 生成的大图（>800px，非上传预览小图）"""
    js = (
        'var imgs=document.querySelectorAll(\'img[src*="estuary"]\');'
        "var count=0,url='';"
        "for(var i=0;i<imgs.length;i++){"
        "if(imgs[i].naturalWidth>800&&imgs[i].naturalHeight>800)"
        "{count++;url=imgs[i].src;}}"
        "count+':'+url;"
    )

    def check():
        r = kimi_safe("evaluate", {"code": js}, session=session)
        val = str(r.get("data", {}).get("value", "0:"))
        parts = val.split(":", 1)
        if parts[0].isdigit() and int(parts[0]) > 0 and len(parts) > 1 and parts[1].startswith("http"):
            return parts[1]
        return None
    return poll_until(check, timeout, POLL_LONG, "DALL-E 生图")


def upload_image_via_kimi(img_path, session=SESSION):
    """用 Kimi WebBridge 原生 upload 功能上传图片"""
    r = kimi("upload", {
        "selector": "#upload-photos",
        "files": [img_path]
    }, session=session, timeout=UPLOAD_TIMEOUT)
    ok = r.get("ok", False)
    val = r.get("data", {})
    if ok and val.get("success"):
        logger.info(f"  Kimi upload 成功: {val.get('fileCount', 0)} 个文件")
        return True
    logger.error(f"  Kimi upload 失败: {r}")
    return False


def fill_chinese(text, session=SESSION):
    return kimi("fill", {"selector": "div.ProseMirror", "value": text}, session=session)


def click_send(session=SESSION):
    return kimi("click", {"selector": 'button[data-testid="send-button"]'}, session=session)


def download_via_network(dest_path, img_url, session=SESSION):
    """network 拦截下载图片"""
    kimi("network", {"cmd": "start"}, session=session)
    time.sleep(0.5)
    try:
        safe_url = json.dumps(img_url)
        fetch_js = (
            '(async()=>{var r=await fetch(' + safe_url + ',{credentials:"include"});'
            'return r.status+":"+r.headers.get("content-type");})()'
        )
        ok = False
        for attempt in range(FETCH_MAX_RETRY):
            r = kimi_safe("evaluate", {"code": fetch_js}, session=session, timeout=30)
            status = str(r.get("data", {}).get("value", ""))
            if status.startswith("200") and "image" in status:
                ok = True
                break
            logger.info(f"Fetch 重试 {attempt + 1}/{FETCH_MAX_RETRY}: {status}")
            time.sleep(2)
        if not ok:
            return False

        time.sleep(1)
        net = kimi("network", {"cmd": "list"}, session=session)
        reqs = net.get("data", {}).get("requests", [])
        rid = None
        # Match the specific image URL, not just any estuary URL
        for req in reqs:
            req_url = req.get("url", "")
            if "estuary" in req_url and img_url and img_url.split("?")[0] in req_url:
                rid = req.get("requestId")
                break
        # Fallback: last estuary request (usually the generated image, not the preview)
        if not rid:
            estuary_reqs = [req for req in reqs if "estuary" in req.get("url", "")]
            if estuary_reqs:
                rid = estuary_reqs[-1].get("requestId")
        if not rid:
            logger.warning("未找到 estuary 请求")
            return False

        detail = kimi("network", {"cmd": "detail", "requestId": rid}, session=session, timeout=DETAIL_TIMEOUT)
        body = detail.get("data", {}).get("body", "")
        if not body or len(body) < IMG_BODY_MIN_LEN:
            logger.warning(f"响应体太小: {len(body)} 字符")
            return False

        img_bytes = base64.b64decode(body)
        if len(img_bytes) < 1000:
            logger.warning(f"解码后图片太小: {len(img_bytes)} bytes")
            return False

        with open(dest_path, 'wb') as f:
            f.write(img_bytes)
        return True
    finally:
        kimi_safe("network", {"cmd": "stop"}, session=session)


def download_fallback(dest_path, session=SESSION):
    """截图 fallback"""
    r = kimi_safe("screenshot", {}, session=session, timeout=15)
    img = r.get("data", {}).get("data", "")
    if not img:
        return False
    padding = 4 - len(img) % 4
    if padding != 4:
        img += '=' * padding
    try:
        img_bytes = base64.b64decode(img)
        with open(dest_path, 'wb') as f:
            f.write(img_bytes)
        return True
    except Exception as e:
        logger.error(f"截图解码失败: {e}")
        return False


# ========== 输入校验 ==========

def validate_image(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"图片不存在: {path}")
    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > MAX_IMG_SIZE_MB:
        raise ValueError(f"图片太大: {size_mb:.1f}MB，上限 {MAX_IMG_SIZE_MB}MB")
    with open(path, 'rb') as f:
        header = f.read(4)
    if header[:2] not in (b'\xff\xd8',) and header[:4] not in (b'\x89PNG', b'GIF8', b'RIFF'):
        logger.warning(f"文件头未知，可能不是图片: {path}")
    return size_mb


# ========== 辅助 ==========

def check_kimi_health() -> bool:
    """检查 Kimi WebBridge 是否可用"""
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:10086/status", timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("running") and data.get("extension_connected")
    except:
        return False


def clear_chat(session=SESSION):
    """清空对话（避免上下文干扰）"""
    kimi_safe("close_session", {}, session=session, timeout=10)
    kimi_safe("navigate", {"url": "https://chatgpt.com", "newTab": True}, session=session)
    time.sleep(2)
    return wait_for_page_ready(session=session)


def _build_session_name(run_token: str, style: str) -> str:
    return f"{SESSION}-{run_token}-{style}"


def _open_chatgpt_session(session: str) -> bool:
    kimi_safe("close_session", {}, session=session, timeout=10)
    kimi("navigate", {"url": "https://chatgpt.com", "newTab": True}, session=session)
    return bool(wait_for_page_ready(session=session))


def _submit_prompt_and_download(prompt: str, output_path: str, session: str) -> Optional[str]:
    logger.info("  填入提示词...")
    fill_chinese(prompt, session=session)
    time.sleep(POLL_MEDIUM)

    logger.info("  发送...")
    if not wait_for_send_button(session=session):
        logger.error("发送按钮未就绪")
        return None
    click_send(session=session)
    time.sleep(POLL_MEDIUM)

    for attempt in range(SEND_MAX_RETRY):
        r = kimi_safe("evaluate", {
            'code': 'document.querySelector("div.ProseMirror")?.innerText?.length'
        }, session=session)
        if r.get("data", {}).get("value", -1) == 0:
            break
        logger.info(f"  重试发送 {attempt + 1}/{SEND_MAX_RETRY}")
        click_send(session=session)
        time.sleep(2)

    logger.info("  等待 DALL-E 生图...")
    img_url = wait_for_image(session=session)
    if not img_url:
        logger.error("生图超时")
        return None

    logger.info("  下载图片...")
    if download_via_network(output_path, img_url, session=session):
        size = os.path.getsize(output_path)
        logger.info(f"  ✅ 已生成: {output_path} ({size} bytes)")
        return output_path

    logger.warning("network 下载失败，截图 fallback...")
    fallback_path = output_path.replace(".png", "_screenshot.png")
    if download_fallback(fallback_path, session=session):
        logger.info(f"  ⚠️ 截图: {fallback_path}")
        return fallback_path
    return None


def generate_single_image(
    product_image_path: str,
    prompt: str,
    output_path: str,
    session: str = SESSION,
) -> Optional[str]:
    """
    生成单张图片：
    1. 上传产品图（Kimi WebBridge 原生 upload）
    2. 填提示词
    3. 发送
    4. 等 DALL-E 生图
    5. 下载
    """
    # 上传（用 Kimi WebBridge 原生 upload，不用 DataTransfer）
    logger.info("  上传产品图片...")
    if not upload_image_via_kimi(product_image_path, session=session):
        logger.error("图片上传失败")
        return None

    # 等预览图出现
    def check_preview():
        r = kimi_safe("evaluate", {
            'code': 'document.querySelectorAll(\'img[src*="estuary"]\').length'
        }, session=session)
        return int(r.get("data", {}).get("value", 0) or 0) > 0
    poll_until(check_preview, PREVIEW_MAX_WAIT, POLL_SHORT, "预览图")
    return _submit_prompt_and_download(prompt, output_path, session=session)


# ========== 公开 API ==========

@dataclass
class ImageResult:
    images: list[str]
    method: str
    provider: str
    model: str
    results: list[dict] = field(default_factory=list)


def generate_images(
    product_name: str,
    output_dir: str,
    product_image_path: Optional[str] = None,
    count: int = 3,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    style_indices: Optional[list[int]] = None,
    prompt_overrides: Optional[list[str]] = None,
) -> ImageResult:
    """
    为产品生成3张小红书风格主图（via Kimi WebBridge + ChatGPT DALL-E）

    Args:
        product_name: 产品名称
        output_dir: 输出目录
        product_image_path: 产品原图路径（用于上传参考）
        count: 生成数量（默认3）
        provider: 忽略（兼容接口）
        api_key: 忽略（兼容接口）
        style_indices: 只生成指定风格索引（0=博主风，1=纯白简约，2=氛围场景）
        prompt_overrides: 指定每个风格的完整提示词，长度按索引对应

    Returns:
        ImageResult
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 检查 Kimi WebBridge
    if not check_kimi_health():
        logger.error("Kimi WebBridge 不可用，请确保浏览器扩展已连接 (http://127.0.0.1:10086)")
        return ImageResult(images=[], method="kimi-webbridge", provider="chatgpt", model="dall-e-3")

    # 读取产品图片
    has_product_image = False
    if product_image_path and os.path.isfile(product_image_path):
        logger.info(f"使用产品原图: {product_image_path}")
        has_product_image = True
    else:
        logger.warning("无产品原图，将使用纯文字提示词生图")

    # 获取3种风格的提示词
    prompts = get_all_image_prompts(product_name)
    style_names = ["style_a", "style_b", "style_c"]
    style_labels = ["博主风", "纯白简约", "氛围场景"]
    if style_indices is None:
        selected_indices = list(range(min(count, len(prompts), len(style_names))))
    else:
        selected_indices = [
            i for i in style_indices
            if isinstance(i, int) and 0 <= i < len(prompts) and i < len(style_names)
        ]
    if not selected_indices:
        return ImageResult(images=[], method="kimi-webbridge", provider="chatgpt", model="dall-e-3")

    run_token = str(int(time.time() * 1000))

    def worker(i: int) -> dict:
        if prompt_overrides and i < len(prompt_overrides) and prompt_overrides[i]:
            prompt = prompt_overrides[i]
        else:
            prompt = prompts[i]

        style = style_names[i]
        session = _build_session_name(run_token, style)
        output_path = os.path.join(output_dir, f"xhs_{style}.png")
        logger.info(f"正在生成第 {i + 1}/{count} 张图片（{style}，session={session}）...")

        result_path = None
        error = ""
        try:
            if not _open_chatgpt_session(session):
                error = "ChatGPT 页面加载超时"
            elif has_product_image:
                result_path = generate_single_image(
                    product_image_path,
                    prompt,
                    output_path,
                    session=session,
                )
            else:
                logger.info("  无原图，纯文字提示...")
                result_path = _submit_prompt_and_download(prompt, output_path, session=session)

            if not result_path and not error:
                error = "生成失败或超时，请重试"
        except Exception as e:
            error = str(e)
            logger.warning(f"图片生成失败（{style}）: {e}")
        finally:
            kimi_safe("close_session", {}, session=session, timeout=10)

        if result_path:
            return {
                "index": i,
                "style": style,
                "label": style_labels[i],
                "status": "image",
                "path": result_path,
                "error": "",
            }
        return {
            "index": i,
            "style": style,
            "label": style_labels[i],
            "status": "failed",
            "path": "",
            "error": error or "生成失败或超时，请重试",
        }

    max_workers = 1 if len(selected_indices) == 1 else min(len(selected_indices), MAX_PARALLEL_WORKERS)
    if max_workers > 1:
        logger.info(f"并行生成 {len(selected_indices)} 张图片，使用 {max_workers} 个独立会话...")

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker, i) for i in selected_indices]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item.get("index", 999))
    images = [
        item["path"]
        for item in results
        if item.get("status") == "image" and item.get("path")
    ]

    return ImageResult(
        images=images,
        method="kimi-webbridge",
        provider="chatgpt",
        model="dall-e-3",
        results=results,
    )
