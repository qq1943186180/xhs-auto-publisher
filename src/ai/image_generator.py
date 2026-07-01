"""
小红书主图生成器 - Kimi WebBridge + ChatGPT DALL-E
用浏览器自动化调 ChatGPT 生图，不需要 OpenAI API Key
3种风格变体：博主风/纯白简约/氛围场景
"""
import os
import json
import base64
import time
import logging
import threading
import uuid
import subprocess
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .prompt_templates import get_all_image_prompts
from src.utils import get_logger
from src.utils.kimi_webbridge import (
    describe_kimi_status,
    ensure_kimi_webbridge,
    read_kimi_status,
)

logger = get_logger("image_generator")

# ========== 常量 ==========
# Kimi WebBridge 地址从环境变量读取，默认 127.0.0.1:10086
KIMI_URL = os.environ.get("KIMI_WEBBRIDGE_URL", "http://127.0.0.1:10086/command")
KIMI_STATUS_URL = KIMI_URL.rsplit("/command", 1)[0] + "/status" if "/command" in KIMI_URL else "http://127.0.0.1:10086/status"
SESSION = "xhs-img-gen"
POLL_SHORT = 1
POLL_MEDIUM = 3
POLL_LONG = 3
IMG_SIZE_THRESHOLD = 1000
IMG_BODY_MIN_LEN = 1000
FETCH_MAX_RETRY = 3
SEND_MAX_RETRY = 2
PREVIEW_MAX_WAIT = 15
PAGE_READY_TIMEOUT = 30
IMAGE_GEN_TIMEOUT = 300
UPLOAD_TIMEOUT = 30
DETAIL_TIMEOUT = 60
MAX_IMG_SIZE_MB = 10
MAX_PARALLEL_WORKERS = 2
UPLOAD_LOCK = threading.Lock()

# 可重试的错误关键字
_RETRYABLE_KEYWORDS = ("timeout", "timed out", "connection", "network", "reset", "refused")


def _hidden_subprocess_kwargs() -> dict:
    """Hide helper console windows when running from the GUI on Windows."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _run_hidden(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.update(_hidden_subprocess_kwargs())
    return subprocess.run(cmd, **kwargs)


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


# ========== API 直连生图（绕过 ChatGPT / Cloudflare）==========

# 优先级从高到低：速度快、质量好的排前面
_API_IMAGE_MODELS = [
    "Kwai-Kolors/Kolors",
    "Tongyi-MAI/Z-Image-Turbo",
    "baidu/ERNIE-Image-Turbo",
    "Tongyi-MAI/Z-Image",
]


def _get_api_client():
    """获取 OpenAI 兼容的 API 客户端（优先 SiliconFlow）。"""
    try:
        from openai import OpenAI
    except ImportError:
        return None, None
    try:
        from .api_key_manager import get_key_manager, Provider
        km = get_key_manager()
        # 优先 OpenAI 兼容 key（通常是 SiliconFlow）
        entry = km.get_key(Provider.OPENAI)
        if not entry:
            entry = km.get_key()
        if not entry:
            return None, None
        client = OpenAI(api_key=entry.api_key, base_url=entry.base_url, timeout=60)
        return client, entry
    except Exception as e:
        logger.debug("获取 API 客户端失败: %s", e)
        return None, None


def _pick_api_image_model(client) -> Optional[str]:
    """从可用模型列表中挑选最佳图片模型。"""
    try:
        available = {m.id for m in client.models.list().data}
    except Exception:
        # 如果无法列出模型，直接尝试默认顺序
        return _API_IMAGE_MODELS[0]
    for model in _API_IMAGE_MODELS:
        if model in available:
            return model
    # 兜底：匹配任何含 image/flux/kolors 的模型
    for mid in available:
        if any(kw in mid.lower() for kw in ("image", "flux", "kolors", "stable", "sdxl")):
            return mid
    return None


def _download_image_from_url(url: str, dest_path: str, timeout: int = 30) -> bool:
    """从 URL 下载图片并保存到本地。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 1000:
            logger.warning("API 图片太小: %d bytes", len(data))
            return False
        with open(dest_path, "wb") as f:
            f.write(data)
        logger.info("  API 图片已下载: %s (%d bytes)", dest_path, len(data))
        return True
    except Exception as e:
        logger.error("下载 API 图片失败: %s", e)
        return False


def generate_single_image_via_api(
    prompt: str,
    output_path: str,
    client=None,
    model: Optional[str] = None,
    size: str = "768x1024",
) -> Optional[str]:
    """通过 OpenAI 兼容 API 直连生成单张图片（不经过 ChatGPT 浏览器）。"""
    if client is None:
        client, entry = _get_api_client()
        if client is None:
            logger.error("无可用 API 客户端")
            return None

    if model is None:
        model = _pick_api_image_model(client)
        if model is None:
            logger.error("未找到可用的图片生成模型")
            return None

    logger.info("  API 直连生图: model=%s, size=%s", model, size)
    try:
        result = client.images.generate(
            model=model,
            prompt=prompt,
            n=1,
            size=size,
        )
        img_data = result.data[0]
        if img_data.url:
            if _download_image_from_url(img_data.url, output_path):
                return output_path
        elif img_data.b64_json:
            img_bytes = base64.b64decode(img_data.b64_json)
            if len(img_bytes) < 1000:
                logger.warning("API b64 图片太小: %d bytes", len(img_bytes))
                return None
            with open(output_path, "wb") as f:
                f.write(img_bytes)
            logger.info("  API b64 图片已保存: %s (%d bytes)", output_path, len(img_bytes))
            return output_path
    except Exception as e:
        logger.error("API 生图失败: %s", e)
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
            'code': """(() => {
                const btn = document.querySelector('button[data-testid="send-button"]');
                if (!btn) return 'no btn';
                const label = btn.getAttribute('aria-label') || '';
                const disabled = btn.disabled;
                return label + '|' + (disabled ? 'disabled' : 'enabled');
            })()"""
        }, session=session)
        val = str(r.get("data", {}).get("value", ""))
        # 发送按钮存在且未禁用
        if "发送" in val and "enabled" in val:
            return True
        return False
    return poll_until(check, timeout, POLL_SHORT, "发送按钮")


def wait_for_image(timeout=IMAGE_GEN_TIMEOUT, session=SESSION):
    """轮询检测 DALL-E 生成的大图（>500px，非上传预览小图）"""
    # 只匹配 estuary 域名（DALL-E生成图），排除 oaiusercontent（可能是上传的参考图回显）
    # 同时排除已存在的图片（通过记录初始图片数量）
    initial_js = (
        'var imgs=document.querySelectorAll(\'img[src*="estuary"]\');'
        "var initCount=0,initUrls=[];"
        "for(var i=0;i<imgs.length;i++){"
        "if(imgs[i].naturalWidth>=500&&imgs[i].naturalHeight>=500)"
        "{initCount++;initUrls.push(imgs[i].src);}}"
        "initCount+'|'+initUrls.join(',');"
    )
    r0 = kimi_safe("evaluate", {"code": initial_js}, session=session)
    init_val = str(r0.get("data", {}).get("value", "0|"))
    init_parts = init_val.split("|", 1)
    init_count = int(init_parts[0]) if init_parts[0].isdigit() else 0
    init_urls = set(init_parts[1].split(",")) if len(init_parts) > 1 else set()
    logger.info("  初始estuary图片数: %s (等待新增)", init_count)

    js = (
        'var imgs=document.querySelectorAll(\'img[src*="estuary"]\');'
        "var count=0,url='';"
        "for(var i=0;i<imgs.length;i++){"
        "if(imgs[i].naturalWidth>=500&&imgs[i].naturalHeight>=500)"
        "{count++;url=imgs[i].src;}}"
        "count+':'+url;"
    )

    _poll_count = [0]
    def check():
        _poll_count[0] += 1
        if _poll_count[0] % 10 == 0:
            elapsed = _poll_count[0] * POLL_LONG
            logger.info("  DALL-E 生图中... 已等待 %ds/%ds", elapsed, timeout)
            # 每60秒输出一次页面诊断
            if _poll_count[0] % 20 == 0:
                _log_page_diagnostics(session, elapsed)
        r = kimi_safe("evaluate", {"code": js}, session=session)
        val = str(r.get("data", {}).get("value", "0:"))
        parts = val.split(":", 1)
        if parts[0].isdigit() and len(parts) > 1 and parts[1].startswith("http"):
            count = int(parts[0])
            url = parts[1]
            # 必须是新增的图片（不在初始URL集合中）
            if count > init_count or url not in init_urls:
                return url
        return None
    result = poll_until(check, timeout, POLL_LONG, "DALL-E 生图")
    if not result:
        # 超时时输出完整诊断
        _log_page_diagnostics(session, timeout, is_timeout=True)
    return result


def _log_page_diagnostics(session, elapsed, is_timeout=False):
    """输出 ChatGPT 页面诊断信息：所有 img 元素、错误文本、按钮状态"""
    tag = "生图超时诊断" if is_timeout else "生图等待诊断"
    try:
        # 列出所有 img 元素的 src 和尺寸
        js_imgs = (
            'var imgs=document.querySelectorAll("img");'
            "var info=[];"
            "for(var i=0;i<Math.min(imgs.length,15);i++){"
            "info.push(imgs[i].src.substring(0,80)+' ['+imgs[i].naturalWidth+'x'+imgs[i].naturalHeight+']');}"
            "info.join('\\n');"
        )
        r = kimi_safe("evaluate", {"code": js_imgs}, session=session)
        imgs_info = str(r.get("data", {}).get("value", ""))
        logger.warning("[%s] 已等待%ds - 页面img元素:", tag, elapsed)
        for line in imgs_info.split("\\n"):
            if line.strip():
                logger.warning("  %s", line.strip())

        # 检查是否有错误提示
        js_errors = (
            'var errs=document.querySelectorAll("[class*=error], [class*=Error], [role=alert], '
            "\[data-testid*=error]\");"
            "var msgs=[];"
            "for(var i=0;i<errs.length;i++){"
            "var t=errs[i].innerText.trim();"
            "if(t&&t.length<200) msgs.push(t);}"
            "msgs.join(' | ');"
        )
        r = kimi_safe("evaluate", {"code": js_errors}, session=session)
        errors = str(r.get("data", {}).get("value", ""))
        if errors.strip():
            logger.warning("[%s] 页面错误提示: %s", tag, errors[:300])

        # 检查发送按钮状态
        js_btn = (
            'var btn=document.querySelector("button[data-testid=send-button]");'
            "btn ? ('btn exists, disabled='+btn.disabled) : 'no send btn';"
        )
        r = kimi_safe("evaluate", {"code": js_btn}, session=session)
        btn_info = str(r.get("data", {}).get("value", ""))
        logger.warning("[%s] 发送按钮: %s", tag, btn_info)
    except Exception as e:
        logger.debug("[%s] 诊断异常: %s", tag, e)


def upload_image_via_kimi(img_path, session=SESSION):
    """用 CDP DOM.setFileInputFiles 上传图片到 ChatGPT（最可靠）"""
    if not os.path.isfile(img_path):
        logger.error("图片文件不存在: %s", img_path)
        return False

    # 方式1: CDP 直连 Edge（最可靠，触发真实文件上传）
    try:
        r = _run_hidden(
            ["curl.exe", "-s", "http://127.0.0.1:9222/json/list"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        tabs = json.loads(r.stdout)
        chatgpt_tabs = [t for t in tabs if 'chatgpt.com' in t.get('url', '')]
        if chatgpt_tabs:
            import websocket as _ws_mod
            ws = _ws_mod.create_connection(chatgpt_tabs[0]['webSocketDebuggerUrl'], timeout=10)
            ws.settimeout(30)
            try:
                def _cdp(method, params=None, cmd_id=1):
                    msg = {'id': cmd_id, 'method': method}
                    if params:
                        msg['params'] = params
                    ws.send(json.dumps(msg))
                    while True:
                        resp = json.loads(ws.recv())
                        if resp.get('id') == cmd_id:
                            return resp

                _cdp('DOM.enable')
                r = _cdp('DOM.getDocument', {'depth': -1}, 1)
                root_id = r['result']['root']['nodeId']
                r = _cdp('DOM.querySelectorAll', {'nodeId': root_id, 'selector': '#upload-photos'}, 2)
                node_ids = r.get('result', {}).get('nodeIds', [])
                if node_ids:
                    _cdp('DOM.setFileInputFiles',
                         {'nodeId': node_ids[0], 'files': [os.path.abspath(img_path)]}, 3)
                    logger.info("  图片上传成功 (CDP): %s", os.path.basename(img_path))
                    return True
            finally:
                try:
                    ws.close()
                except Exception:
                    pass
    except Exception as e:
        logger.debug("  CDP 上传失败，降级: %s", e)

    # 方式2: WebBridge drag-drop 降级
    import base64 as _b64
    with open(img_path, 'rb') as f:
        b64_data = _b64.b64encode(f.read()).decode('ascii')
    filename = os.path.basename(img_path)
    mime = 'image/png' if img_path.lower().endswith('.png') else 'image/jpeg'

    js = """
    (async () => {
      const b64 = 'B64DATA';
      const binaryStr = atob(b64);
      const bytes = new Uint8Array(binaryStr.length);
      for(let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);
      const file = new File([bytes], 'FILENAME', {type: 'MIME'});

      // 策略1: 找到文件上传input，直接设置files
      const fileInputs = document.querySelectorAll('input[type=file]');
      for (const fi of fileInputs) {
        try {
          const dt = new DataTransfer();
          dt.items.add(file);
          fi.files = dt.files;
          fi.dispatchEvent(new Event('change', {bubbles: true}));
          return 'ok-fileinput';
        } catch(e) {}
      }

      // 策略2: drag-drop 事件
      const dt = new DataTransfer();
      dt.items.add(file);
      const editor = document.querySelector('div.ProseMirror') || document.querySelector('form');
      if (!editor) return 'no editor';
      const drop = new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt});
      editor.dispatchEvent(drop);
      editor.dispatchEvent(new DragEvent('dragenter', {bubbles: true, dataTransfer: dt}));
      editor.dispatchEvent(new DragEvent('dragover', {bubbles: true, dataTransfer: dt}));
      editor.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt}));

      // 策略3: 尝试粘贴事件
      try {
        const clipboardData = new DataTransfer();
        clipboardData.items.add(file);
        const pasteEvent = new ClipboardEvent('paste', {
          bubbles: true,
          cancelable: true,
          clipboardData: clipboardData
        });
        editor.dispatchEvent(pasteEvent);
      } catch(e) {}

      return 'ok-dragdrop';
    })()
    """.replace('B64DATA', b64_data).replace('FILENAME', filename).replace('MIME', mime)

    r = kimi_safe("evaluate", {"code": js}, session=session, timeout=UPLOAD_TIMEOUT)
    val = r.get("data", {}).get("value", "")
    if val and val.startswith("ok"):
        logger.info("  图片上传成功 (%s): %s", val, filename)
        # 等待ChatGPT处理上传
        time.sleep(3)
        return True

    logger.error("  图片上传失败: %s", r)
    return False


def fill_chinese(text, session=SESSION):
    r = kimi("fill", {"selector": "div.ProseMirror", "value": text}, session=session)
    # 填入后触发input事件激活发送按钮
    kimi_safe("evaluate", {
        "code": """(() => {
            const editor = document.querySelector('div.ProseMirror');
            if (editor) {
                editor.focus();
                editor.dispatchEvent(new Event('input', {bubbles: true}));
            }
        })()"""
    }, session=session)
    return r


def click_send(session=SESSION):
    # 强制点击（即使按钮 disabled，CDP 上传后可能需要手动触发）
    r = kimi_safe("evaluate", {
        "code": """(() => {
            const btn = document.querySelector('button[data-testid="send-button"]');
            if (!btn) return 'no btn';
            const label = btn.getAttribute('aria-label') || '';
            const wasDisabled = btn.disabled;
            // 临时启用按钮并点击
            btn.disabled = false;
            btn.click();
            // 如果按钮原本是disabled的，尝试用Enter键发送
            if (wasDisabled) {
                const editor = document.querySelector('div.ProseMirror');
                if (editor) {
                    editor.focus();
                    const enterEvent = new KeyboardEvent('keydown', {
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        which: 13,
                        bubbles: true,
                        cancelable: true
                    });
                    editor.dispatchEvent(enterEvent);
                }
            }
            return 'clicked|' + label + '|' + (wasDisabled ? 'was_disabled' : 'was_enabled');
        })()"""
    }, session=session)
    return r


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
            logger.info("Fetch 重试 %s/%s: %s", attempt + 1, FETCH_MAX_RETRY, status)
            time.sleep(2)
        if not ok:
            return False

        time.sleep(1)
        net = kimi("network", {"cmd": "list"}, session=session)
        reqs = net.get("data", {}).get("requests", [])
        rid = None
        for req in reqs:
            req_url = req.get("url", "")
            if "estuary" in req_url and img_url and img_url.split("?")[0] in req_url:
                rid = req.get("requestId")
                break
        if not rid:
            estuary_reqs = [req for req in reqs if "estuary" in req.get("url", "")]
            if estuary_reqs:
                rid = estuary_reqs[-1].get("requestId")
        if not rid:
            # 可能是上传的参考图URL(oaiusercontent)，不是DALL-E生成的图
            all_img_reqs = [req for req in reqs if "oaiusercontent" in req.get("url", "") or "estuary" in req.get("url", "")]
            if all_img_reqs:
                rid = all_img_reqs[-1].get("requestId")
                logger.warning("未找到estuary请求，使用最后一个图片请求: %s", reqs[-1].get("url", "")[:80])
        if not rid:
            logger.warning("未找到 estuary 请求")
            return False

        detail = kimi("network", {"cmd": "detail", "requestId": rid}, session=session, timeout=DETAIL_TIMEOUT)
        body = detail.get("data", {}).get("body", "")
        if not body or len(body) < IMG_BODY_MIN_LEN:
            logger.warning("响应体太小: %s 字符", len(body))
            return False

        img_bytes = base64.b64decode(body)
        if len(img_bytes) < 1000:
            logger.warning("解码后图片太小: %s bytes", len(img_bytes))
            return False

        with open(dest_path, 'wb') as f:
            f.write(img_bytes)
        return True
    finally:
        kimi_safe("network", {"cmd": "stop"}, session=session)


def download_fallback(dest_path, session=SESSION):
    """截图 fallback（含 session 健康检查，防止对离线 session 截图导致崩溃）"""
    try:
        # 先检查 session 是否仍然存活
        health = kimi_safe("evaluate", {"code": "document.readyState"}, session=session, timeout=10)
        ready_state = str(health.get("data", {}).get("value", ""))
        if not ready_state:
            logger.warning("截图 fallback 跳过：session 无响应（可能已离线）")
            return False

        r = kimi_safe("screenshot", {}, session=session, timeout=15)
        img = r.get("data", {}).get("data", "")
        if not img:
            return False
        # 修复 base64 padding bug：原代码 4 - len % 4 可能得到 4（不需要 padding 时）
        padding = (4 - len(img) % 4) % 4
        if padding != 0:
            img += '=' * padding
        img_bytes = base64.b64decode(img)
        with open(dest_path, 'wb') as f:
            f.write(img_bytes)
        return True
    except Exception as e:
        logger.error("截图 fallback 异常: %s", e)
        return False


# ========== 输入校验 ==========

def validate_image(path):
    """使用 Pillow 验证图片完整性"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"图片不存在: {path}")
    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > MAX_IMG_SIZE_MB:
        raise ValueError(f"图片太大: {size_mb:.1f}MB，上限 {MAX_IMG_SIZE_MB}MB")

    # 尝试用 Pillow 打开验证图片完整性
    try:
        from PIL import Image
        with Image.open(path) as img:
            img.verify()  # 验证图片完整性
    except ImportError:
        # Pillow 不可用时回退到文件头检查
        with open(path, 'rb') as f:
            header = f.read(4)
        if header[:2] not in (b'\xff\xd8',) and header[:4] not in (b'\x89PNG', b'GIF8', b'RIFF'):
            logger.warning("文件头未知，可能不是图片: %s", path)
    except Exception as e:
        raise ValueError(f"图片文件损坏: {e}")

    return size_mb


# ========== 辅助 ==========

def check_kimi_health() -> bool:
    """检查 Kimi WebBridge 是否可用"""
    status = ensure_kimi_webbridge(start_if_needed=True, wait_seconds=5, logger=logger)
    return status.ready


def kimi_health_message(start_if_needed: bool = False) -> str:
    """Return a user-facing Kimi WebBridge status message."""
    status = (
        ensure_kimi_webbridge(start_if_needed=True, wait_seconds=5, logger=logger)
        if start_if_needed
        else read_kimi_status()
    )
    return describe_kimi_status(status)


def clear_chat(session=SESSION):
    """清空对话（避免上下文干扰）"""
    kimi_safe("close_session", {}, session=session, timeout=10)
    kimi_safe("navigate", {"url": "https://chatgpt.com", "newTab": True}, session=session)
    time.sleep(2)
    return wait_for_page_ready(session=session)


def _build_session_name(run_token: str, style: str) -> str:
    """使用 uuid 替代时间戳，避免命名冲突"""
    short_id = uuid.uuid4().hex[:8]
    return f"{SESSION}-{run_token}-{style}-{short_id}"


def _is_retryable_error(error: str) -> bool:
    """判断错误是否可重试（网络/超时类）"""
    error_lower = error.lower()
    return any(kw in error_lower for kw in _RETRYABLE_KEYWORDS)


def _open_chatgpt_session(session: str) -> bool:
    kimi_safe("close_session", {}, session=session, timeout=10)
    kimi("navigate", {"url": "https://chatgpt.com", "newTab": True}, session=session)
    if not wait_for_page_ready(session=session):
        # 页面未就绪，检查是否是 Cloudflare 拦截或登录问题
        page_info = _check_chatgpt_page_error(session)
        if page_info:
            raise RuntimeError(page_info)
        return False
    return True


def _check_chatgpt_page_error(session: str) -> str:
    """检查 ChatGPT 页面是否有 Cloudflare 拦截、登录墙等明确错误。"""
    r = kimi_safe("evaluate", {
        "code": """(() => {
            const body = document.body.innerText || '';
            const url = window.location.href;
            if (/Unable to load site|Access denied|Cloudflare|Ray ID|blocked/i.test(body)) {
                const ipMatch = body.match(/IP[:\\s]+([\\d.]+)/);
                return 'CLOUDFLARE_BLOCK:' + (ipMatch ? ipMatch[1] : '') + ':' + body.substring(0, 150);
            }
            if (/login|sign in|log in/i.test(body) && !document.querySelector('div.ProseMirror')) {
                return 'LOGIN_REQUIRED:' + url;
            }
            if (/chatgpt\\.com.*\\?/i.test(url) && !document.querySelector('div.ProseMirror')) {
                return 'REDIRECT:' + url;
            }
            return '';
        })()"""
    }, session=session, timeout=10)
    val = str(r.get("data", {}).get("value", ""))
    if val.startswith("CLOUDFLARE_BLOCK:"):
        ip = val.split(":")[1] if ":" in val else ""
        return f"ChatGPT 被 Cloudflare 拦截（IP: {ip}），请更换代理/VPN 后重试"
    if val.startswith("LOGIN_REQUIRED:"):
        return "ChatGPT 未登录，请在浏览器中登录 ChatGPT 后重试"
    if val.startswith("REDIRECT:"):
        return f"ChatGPT 页面异常跳转: {val[9:60]}，请检查网络和登录状态"
    return ""


def _verify_prompt_sent(session: str) -> bool:
    """验证提示词是否成功发送：编辑器清空 或 有生成中指示。"""
    js = """(() => {
        // 检查1: 编辑器文本是否已清空
        var editor = document.querySelector('div.ProseMirror');
        var editorEmpty = !editor || (editor.innerText || '').trim().length === 0;

        // 检查2: 是否有"停止生成"按钮（表示 DALL-E 正在工作）
        var stopBtn = document.querySelector('[data-testid="stop-button"]');
        var hasStop = !!stopBtn;

        // 检查3: 是否有 loading/生成中 动画
        var loading = document.querySelector('[class*="loading"], [class*="generating"], [class*="typing"]');
        var hasLoading = loading && loading.offsetParent !== null;

        // 检查4: 是否有助手回复区域（表示有对话在进行）
        var assistantMsg = document.querySelector('[data-message-author-role="assistant"]');
        var hasAssistant = !!assistantMsg;

        var result = editorEmpty || hasStop || hasLoading || hasAssistant;
        return result.toString() + '|editor=' + editorEmpty + '|stop=' + hasStop + '|loading=' + hasLoading + '|assistant=' + hasAssistant;
    })()"""
    r = kimi_safe("evaluate", {"code": js}, session=session)
    val = str(r.get("data", {}).get("value", ""))
    # 解析结果
    parts = val.split("|")
    is_sent = parts[0].strip() == "true" if parts else False
    logger.info("  发送验证: %s (%s)", "通过" if is_sent else "失败", val[:120])
    return is_sent


def _editor_text_length(session: str) -> int:
    r = kimi_safe("evaluate", {
        "code": 'document.querySelector("div.ProseMirror")?.innerText?.trim()?.length ?? -1'
    }, session=session, timeout=10)
    try:
        return int(r.get("data", {}).get("value", -1))
    except (TypeError, ValueError):
        return -1


def _webbridge_fill_and_send(prompt: str, session: str) -> bool:
    logger.info("  填入提示词...")
    fill_chinese(prompt, session=session)
    time.sleep(POLL_MEDIUM)

    # 检查发送按钮状态
    r = kimi_safe("evaluate", {
        'code': """(() => {
            const btn = document.querySelector('button[data-testid="send-button"]');
            if (!btn) return 'no btn';
            const label = btn.getAttribute('aria-label') || '';
            return label + '|' + (btn.disabled ? 'disabled' : 'enabled');
        })()"""
    }, session=session)
    btn_status = str(r.get("data", {}).get("value", ""))
    logger.info("  发送按钮状态: %s", btn_status)

    # 如果按钮disabled，等待它变为enabled（最多10秒）
    if "disabled" in btn_status:
        logger.info("  发送按钮disabled，等待激活...")
        for _ in range(10):
            time.sleep(1)
            r = kimi_safe("evaluate", {
                'code': """(() => {
                    const btn = document.querySelector('button[data-testid="send-button"]');
                    if (!btn) return 'no btn';
                    return btn.disabled ? 'disabled' : 'enabled';
                })()"""
            }, session=session)
            status = str(r.get("data", {}).get("value", ""))
            if "enabled" in status:
                logger.info("  发送按钮已激活")
                break
        else:
            logger.warning("  发送按钮等待10秒仍disabled")

    logger.info("  发送...")
    click_send(session=session)
    time.sleep(POLL_MEDIUM)

    for attempt in range(SEND_MAX_RETRY):
        if _verify_prompt_sent(session):
            return True
        length = _editor_text_length(session)
        logger.info("  重试发送 %s/%s（编辑器剩余 %s 字）", attempt + 1, SEND_MAX_RETRY, length)
        click_send(session=session)
        time.sleep(2)

    return _verify_prompt_sent(session)


def _submit_prompt_and_download(prompt: str, output_path: str, session: str) -> Optional[str]:
    # 截断过长的提示词（ChatGPT对超长提示词可能无法发送）
    max_prompt_len = 3000
    if len(prompt) > max_prompt_len:
        logger.warning("提示词过长(%s字)，截断到%s字", len(prompt), max_prompt_len)
        prompt = prompt[:max_prompt_len]

    sent = _webbridge_fill_and_send(prompt, session=session)
    if not sent:
        logger.warning("WebBridge 发送未确认，尝试 CDP 兜底发送")
        sent = _cdp_fill_and_send(prompt)
        if sent:
            time.sleep(2)
            sent = _verify_prompt_sent(session)

    if not sent:
        page_error = _check_chatgpt_page_error(session)
        if page_error:
            raise RuntimeError(page_error)
        logger.error("提示词未成功发送（编辑器仍有文本且无生成指示），跳过 DALL-E 等待")
        return None

    logger.info("  等待 DALL-E 生图...")
    img_url = wait_for_image(session=session)
    if not img_url:
        logger.error("生图超时")
        return None

    logger.info("  下载图片...")
    if download_via_network(output_path, img_url, session=session):
        size = os.path.getsize(output_path)
        logger.info("  ✅ 已生成: %s (%s bytes)", output_path, size)
        return output_path

    logger.warning("network 下载失败，截图 fallback...")
    try:
        fallback_path = output_path.replace(".png", "_screenshot.png")
        if download_fallback(fallback_path, session=session):
            logger.info("  ⚠️ 截图: %s", fallback_path)
            return fallback_path
    except Exception as e:
        logger.error("截图 fallback 外层异常: %s", e)
    return None


def _cdp_fill_and_send(prompt: str) -> bool:
    """用 CDP 直接填写提示词并发送（绕过 WebBridge）"""
    try:
        r = _run_hidden(
            ["curl.exe", "-s", "http://127.0.0.1:9222/json/list"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        tabs = json.loads(r.stdout)
        ct = [t for t in tabs if 'chatgpt.com' in t.get('url', '')]
        if not ct:
            return False
        import websocket as _ws_mod
        ws = _ws_mod.create_connection(ct[0]['webSocketDebuggerUrl'], timeout=10)
        ws.settimeout(30)
        try:
            def _cdp(method, params=None, cmd_id=1):
                msg = {'id': cmd_id, 'method': method}
                if params:
                    msg['params'] = params
                ws.send(json.dumps(msg))
                while True:
                    resp = json.loads(ws.recv())
                    if resp.get('id') == cmd_id:
                        return resp

            _cdp('Runtime.enable')
            # 填提示词
            safe_prompt = json.dumps(prompt)
            _cdp('Runtime.evaluate', {'expression': f"""
                (() => {{
                    const editor = document.querySelector('div.ProseMirror');
                    if (!editor) return 'no editor';
                    editor.focus();
                    editor.innerHTML = '<p>' + {safe_prompt} + '</p>';
                    editor.dispatchEvent(new Event('input', {{bubbles: true}}));
                    return 'filled';
                }})()
            """, 'returnByValue': True}, 10)

            time.sleep(1)

            # 强制发送
            _cdp('Runtime.evaluate', {'expression': """
                (() => {
                    const btn = document.querySelector('button[data-testid="send-button"]');
                    if (!btn) return 'no btn';
                    btn.disabled = false;
                    btn.click();
                    return 'clicked';
                })()
            """, 'returnByValue': True}, 11)

            return True
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception as e:
        logger.debug("CDP fill/send 失败: %s", e)
        return False


def _composer_attachment_count(session=SESSION) -> int:
    """Best-effort count of uploaded attachments visible in the composer."""
    js = r"""
(() => {
  const root = document.querySelector('form') || document;
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 8 && rect.height > 8 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const selectors = [
    'img[src^="blob:"]',
    'img[src^="data:image"]',
    'img[src*="oaiusercontent"]',
    'img[src*="estuary"]',
    '[data-testid*="attachment"]',
    '[data-testid*="file"]',
    '[aria-label*="Upload"]',
    '[aria-label*="上传"]',
    '[aria-label*="附件"]'
  ];
  const nodes = Array.from(root.querySelectorAll(selectors.join(','))).filter(visible);
  const fileCount = Array.from(document.querySelectorAll('input[type=file]'))
    .reduce((sum, input) => sum + ((input.files && input.files.length) || 0), 0);
  return nodes.length + fileCount;
})()
"""
    r = kimi_safe("evaluate", {"code": js}, session=session)
    try:
        return int(r.get("data", {}).get("value", 0) or 0)
    except (TypeError, ValueError):
        return 0


def wait_for_upload_preview(before_count: int = 0, timeout=PREVIEW_MAX_WAIT, session=SESSION) -> bool:
    """Wait until the current ChatGPT session shows the uploaded reference image."""
    def check():
        return _composer_attachment_count(session=session) > before_count

    return bool(poll_until(check, timeout, POLL_SHORT, "上传预览图"))


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
    with UPLOAD_LOCK:
        logger.info("  上传产品图片...")
        before_count = _composer_attachment_count(session=session)
        logger.info("  上传前附件数: %s", before_count)
        if not upload_image_via_kimi(product_image_path, session=session):
            logger.error("图片上传失败")
            return None
        after_count = _composer_attachment_count(session=session)
        logger.info("  上传后附件数: %s (之前: %s)", after_count, before_count)
        if after_count <= before_count:
            logger.warning("附件数未增加，drag-drop可能未生效，重试上传...")
            # 再试一次
            if not upload_image_via_kimi(product_image_path, session=session):
                logger.error("重试上传失败")
                return None
            after_count = _composer_attachment_count(session=session)
            logger.info("  重试后附件数: %s", after_count)
        # 等待ChatGPT处理附件上传（关键！发送按钮需要附件处理完成才会enabled）
        logger.info("  等待ChatGPT处理附件...")
        time.sleep(5)
        # 检查发送按钮是否已激活
        btn_r = kimi_safe("evaluate", {
            "code": """(() => {
                const btn = document.querySelector('button[data-testid="send-button"]');
                if (!btn) return 'no btn';
                return btn.getAttribute('aria-label') + '|' + (btn.disabled ? 'disabled' : 'enabled');
            })()"""
        }, session=session)
        btn_status = str(btn_r.get("data", {}).get("value", ""))
        logger.info("  附件处理后发送按钮: %s", btn_status)
        if not wait_for_upload_preview(before_count, timeout=PREVIEW_MAX_WAIT, session=session):
            logger.warning("未检测到附件预览，但仍继续尝试发送")
    return _submit_prompt_and_download(prompt, output_path, session=session)


# ========== 公开 API ==========

@dataclass
class ImageResult:
    images: list[str]
    method: str
    provider: str
    model: str
    results: list[dict] = field(default_factory=list)


def _worker_result(
    index: int,
    style: str,
    label: str,
    result_path: Optional[str],
    error: str = "",
    method: str = "kimi-webbridge",
    provider: str = "chatgpt",
    model: str = "dall-e-3",
) -> dict:
    if result_path:
        return {
            "index": index,
            "style": style,
            "label": label,
            "status": "image",
            "path": result_path,
            "error": "",
            "method": method,
            "provider": provider,
            "model": model,
        }
    return {
        "index": index,
        "style": style,
        "label": label,
        "status": "failed",
        "path": "",
        "error": error or "生成失败或超时，请重试",
        "method": method,
        "provider": provider,
        "model": model,
    }


def generate_images(
    product_name: str,
    output_dir: str,
    product_image_path: Optional[str] = None,
    count: int = 3,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    style_indices: Optional[list[int]] = None,
    prompt_overrides: Optional[list[str]] = None,
    product_context: str = "",
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
    style_names = ["style_a", "style_b", "style_c"]
    style_labels = ["博主风", "纯白简约", "氛围场景"]
    if style_indices is None:
        selected_indices = list(range(min(count, len(style_names))))
    else:
        selected_indices = [
            i for i in style_indices
            if isinstance(i, int) and 0 <= i < len(style_names)
        ]
    if not selected_indices:
        return ImageResult(images=[], method="kimi-webbridge", provider="chatgpt", model="dall-e-3")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 检查 Kimi WebBridge
    kimi_status = ensure_kimi_webbridge(start_if_needed=True, wait_seconds=8, logger=logger)
    kimi_ready = kimi_status.ready
    use_api_only = False

    if not kimi_ready:
        message = describe_kimi_status(kimi_status)
        logger.warning("Kimi WebBridge 不可用: %s，尝试 API 直连生图", message)
        # 检查 API 直连是否可用
        api_client, api_entry = _get_api_client()
        if api_client is not None:
            use_api_only = True
            logger.info("使用 API 直连生图（%s）", api_entry.base_url)
        else:
            logger.error("Kimi 不可用且无 API 客户端")
            return ImageResult(
                images=[],
                method="kimi-webbridge",
                provider="chatgpt",
                model="dall-e-3",
                results=[
                    {
                        "index": i,
                        "style": style_names[i],
                        "label": style_labels[i],
                        "status": "failed",
                        "path": "",
                        "error": message,
                    }
                    for i in selected_indices
                ],
            )

    # 读取产品图片
    has_product_image = False
    if product_image_path and os.path.isfile(product_image_path):
        logger.info("使用产品原图: %s", product_image_path)
        has_product_image = True
    else:
        logger.warning("无产品原图，将使用纯文字提示词生图")

    # 获取3种风格的提示词
    prompts = get_all_image_prompts(
        product_name,
        product_context=product_context,
        has_attachment=has_product_image,
    )

    run_token = str(int(time.time() * 1000))

    def worker(i: int) -> dict:
        if prompt_overrides and i < len(prompt_overrides) and prompt_overrides[i]:
            prompt = prompt_overrides[i]
        else:
            prompt = prompts[i]

        style = style_names[i]
        session = _build_session_name(run_token, style)
        output_path = os.path.join(output_dir, f"xhs_{style}.png")
        logger.info("正在生成第 %s/%s 张图片（%s，session=%s）...", i + 1, count, style, session)

        result_path = None
        error = ""
        method = "kimi-webbridge"
        provider = "chatgpt"
        model_name = "dall-e-3"

        # ── 模式 A：API 直连（Kimi 不可用或主动降级）──
        if use_api_only:
            logger.info("  [API 直连] 生成 %s ...", style)
            result_path = generate_single_image_via_api(prompt, output_path)
            if result_path:
                method = "api-direct"
                provider = "siliconflow"
                model_name = _pick_api_image_model(_get_api_client()[0]) or "Kolors"
            else:
                error = "API 直连生图失败，请检查网络和 API Key"
            return _worker_result(i, style, style_labels[i], result_path, error, method, provider, model_name)

        # ── 模式 B：Kimi + ChatGPT（Cloudflare 拦截时降级到 API）──
        try:
            if not check_kimi_health():
                error = "Kimi WebBridge 不可用"
            elif not _open_chatgpt_session(session):
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
        except RuntimeError as e:
            error_msg = str(e)
            # Cloudflare 拦截或登录问题 → 降级到 API 直连
            if "Cloudflare" in error_msg or "拦截" in error_msg or "未登录" in error_msg:
                logger.warning("ChatGPT 不可用（%s），降级到 API 直连生图", error_msg)
                result_path = generate_single_image_via_api(prompt, output_path)
                if result_path:
                    method = "api-direct"
                    provider = "siliconflow"
                    model_name = _pick_api_image_model(_get_api_client()[0]) or "Kolors"
                    error = ""
                else:
                    error = f"{error_msg}；API 直连也失败"
            else:
                error = error_msg
        except Exception as e:
            error = str(e)
            if _is_retryable_error(error):
                logger.warning("图片生成遇到可重试错误（%s）: %s", style, e)
            else:
                logger.error("图片生成遇到不可重试错误（%s）: %s", style, e)
        finally:
            kimi_safe("close_session", {}, session=session, timeout=10)

        return _worker_result(i, style, style_labels[i], result_path, error, method, provider, model_name)

    max_workers = 1 if len(selected_indices) == 1 else min(len(selected_indices), MAX_PARALLEL_WORKERS)
    if max_workers > 1:
        logger.info("并行生成 %s 张图片，使用 %s 个独立会话...", len(selected_indices), max_workers)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker, i) for i in selected_indices]
        for future in as_completed(futures):
            try:
                results.append(future.result(timeout=400))
            except FuturesTimeoutError:
                logger.error("Image worker timed out after 400s")
                results.append(_worker_result(-1, "", "", "", "图片生成超时", "timeout", "", ""))
            except Exception as exc:
                logger.error("Image worker raised exception: %s", exc)
                results.append(_worker_result(-1, "", "", "", str(exc), "error", "", ""))

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
