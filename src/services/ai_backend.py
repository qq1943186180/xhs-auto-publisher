"""
AI Backend Service - 从 main_window.py 抽取
AI 生成逻辑、图片重试、笔记生图
通过信号通知 UI 更新
"""
import os
import re
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal

from src.utils import get_logger

logger = get_logger("ai_backend")

COLLECTED_DIR = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "collected")
PRODUCTS_JSON = os.path.join(COLLECTED_DIR, "products_simple.json")
CONFIG_JSON = os.path.join(os.path.expanduser("~"), ".xhs-publisher", "config.json")
GENERATED_IMAGES_DIR = Path.home() / ".xhs-publisher" / "generated_images"
COLLECTED_IMAGES_PER_PRODUCT = 5


def _safe_dir_name(text: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text or "product").strip(" ._")
    return name[:48] or "product"


def _new_image_output_dir(product_name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = GENERATED_IMAGES_DIR / f"{stamp}_{_safe_dir_name(product_name)}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir)


def _reuse_or_create_image_output_dir(product_name: str, existing_images: list[str]) -> str:
    for image in existing_images or []:
        if image and os.path.exists(image):
            parent = Path(image).parent
            parent.mkdir(parents=True, exist_ok=True)
            return str(parent)
    return _new_image_output_dir(product_name)


def _images_per_product_config() -> int:
    try:
        if os.path.exists(CONFIG_JSON):
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                config = json.load(f)
            value = int(config.get("images_per_product", COLLECTED_IMAGES_PER_PRODUCT))
            return max(1, min(9, value))
    except Exception as e:
        logger.warning("Load images_per_product config failed: %s", e)
    return COLLECTED_IMAGES_PER_PRODUCT


def _product_image_context(product: dict | None, extra: str = "") -> str:
    product = product or {}
    parts = []
    for key in ("title", "name", "category", "description", "tags", "price"):
        value = product.get(key)
        if isinstance(value, (list, tuple)):
            value = " ".join(str(item) for item in value if item)
        if value:
            parts.append(f"{key}: {value}")
    if extra:
        parts.append(str(extra))
    return "\n".join(parts)[:1200]


def _download_product_image_from_url(url: str, product_name: str = "") -> str:
    """从 main_images URL 下载图片到临时文件，作为生图参考图。
    返回本地文件路径（JPG格式），失败返回空字符串。
    """
    import requests
    from PIL import Image as PILImage
    import io as _io
    try:
        # 获取高清JPG版本：w/140 -> w/1080, format/webp -> format/jpg
        hd_url = url
        if "w/140" in hd_url:
            hd_url = hd_url.replace("w/140", "w/1080")
        if "format/webp" in hd_url:
            hd_url = hd_url.replace("format/webp", "format/jpg")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.xiaohongshu.com/",
        }
        # 先尝试高清JPG URL，失败回退高清WEBP(转换)，最后原始URL
        urls_to_try = [hd_url]
        if "format/jpg" in hd_url:
            webp_url = hd_url.replace("format/jpg", "format/webp")
            urls_to_try.append(webp_url)
        urls_to_try.append(url)

        for try_url in urls_to_try:
            try:
                resp = requests.get(try_url, timeout=15, headers=headers)
                if resp.status_code != 200 or len(resp.content) < 500:
                    continue

                # 用Pillow打开并统一转为JPG格式（ChatGPT不支持WEBP上传）
                pil_img = PILImage.open(_io.BytesIO(resp.content))
                if pil_img.mode in ("RGBA", "P", "LA", "L"):
                    pil_img = pil_img.convert("RGB")

                safe_name = _safe_dir_name(product_name) if product_name else "ref"
                tmp_dir = Path.home() / ".xhs-publisher" / "ref_images"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                tmp_path = str(tmp_dir / f"{safe_name}.jpg")

                # 保存为真正的JPG格式
                pil_img.save(tmp_path, format="JPEG", quality=95)
                logger.info("已下载参考图(JPG): %s -> %s (%sx%s, %s bytes)",
                            try_url[:60], tmp_path, pil_img.size[0], pil_img.size[1],
                            os.path.getsize(tmp_path))
                return tmp_path
            except Exception as e:
                logger.warning("下载参考图失败 (%s): %s", try_url[:60], e)
                continue
    except Exception as e:
        logger.error("下载参考图异常: %s", e)
    return ""


def _resolve_product_image(product: dict | None) -> str:
    """获取商品参考图路径。
    优先 local_images（本地图），为空时从 main_images URL 下载到临时文件。
    返回本地文件路径，无图返回空字符串。
    """
    if not product:
        return ""
    # 1. 优先使用本地图片
    local_imgs = product.get("local_images", [])
    for img in local_imgs:
        if img and os.path.exists(img):
            return img
    # 2. 本地图为空，从 main_images URL 下载
    main_imgs = product.get("main_images", [])
    if main_imgs:
        product_name = product.get("title", "") or product.get("name", "")
        logger.info("local_images为空，从URL下载参考图: %s", main_imgs[0][:60])
        return _download_product_image_from_url(main_imgs[0], product_name)
    return ""


def _extract_selling_points(product: dict | None) -> str:
    """从产品数据中提取核心卖点，供 LLM 生成文案使用。"""
    product = product or {}
    points = []
    # 从 tags 提取
    tags = product.get("tags")
    if isinstance(tags, list):
        points.extend(str(t) for t in tags if t)
    elif isinstance(tags, str) and tags:
        points.append(tags)
    # 从 extra_data / sku_data 提取关键属性
    for key in ("extra_data", "sku_data"):
        data = product.get(key)
        if isinstance(data, dict):
            for k in ("材质", "颜色", "风格", "适用场景", "材质", "产地", "规格"):
                v = data.get(k)
                if v:
                    points.append(f"{k}: {v}")
        elif isinstance(data, list):
            for item in data[:5]:
                if isinstance(item, str) and item:
                    points.append(item)
    # 从 description 提取第一句作为补充
    desc = product.get("description", "")
    if desc and not points:
        first_sentence = desc.split("。")[0] if "。" in desc else desc[:80]
        points.append(first_sentence)
    return "；".join(points)[:300]


def _image_error_summary(image_results: list[dict]) -> str:
    messages = []
    for item in image_results or []:
        error = (item or {}).get("error", "")
        if error and error not in messages:
            messages.append(error)
    return "；".join(messages)[:800]


def _append_once(messages: list[str], message: str):
    if message and message not in messages:
        messages.append(message)


class AIBackend(QObject):
    """AI generation backend - 两轮生成：方向 → 文案"""
    finished = pyqtSignal(dict)
    direction_done = pyqtSignal(dict)  # 第一轮完成信号
    images_ready = pyqtSignal(dict)    # 图片生成完毕立即通知 UI（不等文案）
    image_retry_done = pyqtSignal(dict)
    note_image_done = pyqtSignal(dict)
    step_changed = pyqtSignal(str, str)  # (step_key, step_label)
    content_regenerated = pyqtSignal(dict)  # 文案重生成完成
    images_regenerated = pyqtSignal(dict)   # 图片重生成完成

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_generating = False
        self._gen_counter = 0
        self._finished_lock = threading.Lock()

    def generate(self, product, style="种草", provider=None, model=None, content_template="", search_results=""):
        # Re-entry guard
        if self._is_generating:
            logger.warning("generate() called while already generating, ignoring")
            return
        self._is_generating = True
        self._gen_counter += 1
        current_gen = self._gen_counter

        # Store content_template and search_results for use in _run
        self._content_template = content_template
        self._search_results = search_results

        # Single-emission guard for finished signal
        _finished_flag = [False]

        def _emit_finished_once(result_dict):
            with self._finished_lock:
                if _finished_flag[0]:
                    logger.warning("finished signal already emitted, skipping duplicate")
                    return
                if current_gen != self._gen_counter:
                    logger.warning("stale generation %s (current=%s), skipping emit", current_gen, self._gen_counter)
                    return
                _finished_flag[0] = True
                self._is_generating = False
                self.finished.emit(result_dict)

        def _run():
            try:
                from src.ai.api_key_manager import get_key_manager, Provider as KMProvider
                km = get_key_manager()

                product_name = product.get("title", "")
                desc = product.get("description", "") or product_name
                price = str(product.get("price", "")) or "未知"
                # 从 tags / extra_data 中提取卖点
                selling_points = _extract_selling_points(product)

                errors = []
                has_llm_key = km.has_keys()

                # 如果指定了 provider，转换为 Provider 枚举
                llm_provider = None
                if provider:
                    try:
                        llm_provider = KMProvider(provider)
                    except ValueError:
                        pass

                # ========================================
                # 第一轮：方向生成
                # ========================================
                self.step_changed.emit("direction_generating", "方向生成中")
                logger.info("第一轮：生成内容方向...")
                directions_data = []
                if has_llm_key:
                    try:
                        from src.ai.direction_generator import generate_directions
                        dir_result = generate_directions(
                            product_name=product_name,
                            description=desc,
                            price=price,
                            selling_points=selling_points,
                            style=style,
                            category=product.get("category", ""),
                            provider=llm_provider,
                        )
                        if dir_result.provider == "template":
                            _append_once(
                                errors,
                                "LLM 方向生成未成功，已使用本地模板兜底（常见原因：接口限流、Key 不可用或返回格式异常）",
                            )
                        directions_data = [
                            {
                                "id": d.id,
                                "name": d.name,
                                "target_audience": d.target_audience,
                                "angle": d.angle,
                                "hook_type": d.hook_type,
                                "style_hint": d.style_hint,
                            }
                            for d in dir_result.directions
                        ]
                        logger.info("方向生成完成: %s", [d['name'] for d in directions_data])
                    except Exception as e:
                        errors.append(f"方向生成失败: {e}")
                        logger.warning("Direction generation failed: %s", e)

                if not directions_data:
                    # 兜底方向
                    from src.ai.direction_generator import _DEFAULT_DIRECTIONS
                    directions_data = list(_DEFAULT_DIRECTIONS)
                    logger.info("使用兜底方向: %s", [d['name'] for d in directions_data])

                # 通知 UI 第一轮完成
                logger.info("发射 direction_done 信号，方向数: %d", len(directions_data))
                self.direction_done.emit({"directions": directions_data})

                # ========================================
                # 第二轮：文案 + 图片 并行生成
                # ========================================
                from concurrent.futures import ThreadPoolExecutor, as_completed
                import threading as _threading

                images = []
                image_results = []
                image_warnings = []

                # --- 图片生成（独立线程） ---
                def _gen_images_thread():
                    from src.ai.image_generator import check_kimi_health, kimi_health_message
                    if not check_kimi_health():
                        image_warnings.append(kimi_health_message(start_if_needed=True))
                        return
                    try:
                        from src.ai.image_generator import generate_images
                        output_dir = _new_image_output_dir(product_name)
                        product_img = _resolve_product_image(product)
                        if product_img:
                            logger.info("生图参考图: %s", product_img)
                        else:
                            logger.warning("无参考图，将使用纯文字生图")
                        img_result = generate_images(
                            product_name=product_name,
                            output_dir=output_dir,
                            product_image_path=product_img,
                            count=3,
                            product_context=_product_image_context(product),
                        )
                        images.extend(img_result.images)
                        image_results.extend(img_result.results)
                        if not img_result.images:
                            detail = _image_error_summary(img_result.results)
                            image_warnings.append(f"图片生成失败：{detail}" if detail else "图片生成失败，请检查 ChatGPT 登录状态")
                        elif len(img_result.images) < 3:
                            image_warnings.append(f"图片生成不完整：已生成 {len(img_result.images)}/3 张，可点击缺失图片重试")
                    except Exception as e:
                        image_warnings.append(f"图片生成失败: {e}")
                        logger.warning("Image generation failed: %s", e)

                self.step_changed.emit("image_generating", "生图等待中")
                image_thread = _threading.Thread(target=_gen_images_thread, daemon=True, name="images")
                image_thread.start()

                # --- 文案生成（主线程，每方向并行） ---
                self.step_changed.emit("content_generating", "文案生成中")
                all_posts = []
                if has_llm_key:
                    posts_lock = _threading.Lock()

                    def _gen_one_direction(dir_data):
                        """在线程池中为单个方向生成 3 篇文案"""
                        dir_name = dir_data["name"]
                        logger.info("第二轮：方向「%s」生成 3 篇文案...", dir_name)
                        local_posts = []
                        local_errors = []
                        try:
                            from src.ai.content_generator import generate_direction_content
                            dir_content = generate_direction_content(
                                product_name=product_name,
                                description=desc,
                                price=price,
                                selling_points=selling_points,
                                direction=dir_data,
                                style=style,
                                provider=llm_provider,
                                content_template=getattr(self, '_content_template', '') or "",
                                search_results=getattr(self, '_search_results', '') or "",  # 搜索结果
                            )
                            if dir_content.provider == "template":
                                local_errors.append(
                                    f"方向「{dir_name}」文案未由 LLM 生成，已使用本地模板兜底"
                                )
                            for post in dir_content.posts:
                                local_posts.append({
                                    "direction_id": dir_data["id"],
                                    "direction_name": dir_name,
                                    "hook_style": post.hook_style,
                                    "title": post.title,
                                    "content": post.content,
                                    "tags": " ".join(post.tags) if post.tags else "",
                                })
                        except Exception as e:
                            local_errors.append(f"方向「{dir_name}」文案生成失败: {e}")
                            logger.warning("Content gen for direction %s failed: %s", dir_name, e)
                        return local_posts, local_errors

                    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="content") as pool:
                        future_map = {
                            pool.submit(_gen_one_direction, dd): dd
                            for dd in directions_data
                        }
                        for future in as_completed(future_map):
                            posts_chunk, err_chunk = future.result()
                            with posts_lock:
                                all_posts.extend(posts_chunk)
                                for em in err_chunk:
                                    _append_once(errors, em)

                    # 按方向顺序排序，保证展示稳定
                    dir_order = {d["id"]: i for i, d in enumerate(directions_data)}
                    all_posts.sort(key=lambda p: (dir_order.get(p["direction_id"], 99), p.get("hook_style", "")))

                # 对没有生成任何帖子的方向用模板兜底
                for dir_data in directions_data:
                    dir_posts = [p for p in all_posts if p["direction_id"] == dir_data["id"]]
                    if not dir_posts:
                        from src.ai.content_generator import _generate_template_posts
                        template_posts = _generate_template_posts(
                            product_name,
                            desc,
                            dir_data,
                            style=style,
                        )
                        for tp in template_posts:
                            all_posts.append({
                                "direction_id": dir_data["id"],
                                "direction_name": dir_data["name"],
                                "hook_style": tp.hook_style,
                                "title": tp.title,
                                "content": tp.content,
                                "tags": " ".join(tp.tags) if tp.tags else "",
                            })

                # 取第一篇的标题作为默认展示
                best_title = all_posts[0]["title"] if all_posts else product_name

                # 等待图片线程完成（如果文案先结束的话）
                image_thread.join(timeout=420)

                # 如果看门狗已经发射了 finished 信号（超时），不再发射 images_ready
                # 因为 _on_ai_done 已经跑完、UI 状态已更新，再来 images_ready 会崩
                if _finished_flag[0]:
                    logger.warning("finished already emitted (watchdog?), skipping images_ready + result")
                    return

                # 图片生成完毕，在主线程中通知 UI 显示（避免跨线程 GUI 信号问题）
                self.images_ready.emit({
                    "images": list(images),
                    "image_results": list(image_results),
                })
                # 合并图片警告到总 errors
                for w in image_warnings:
                    _append_once(errors, w)

                result = {
                    "title": best_title,
                    "content": all_posts[0]["content"] if all_posts else "",
                    "tags": all_posts[0]["tags"] if all_posts else "",
                    "images": images,
                    "image_results": image_results,
                    "product_name": product_name,
                    "posts": all_posts,       # 全部 9 篇
                    "directions": directions_data,
                }
                if errors:
                    result["warnings"] = errors

                if not _finished_flag[0]:
                    self.step_changed.emit("completed", "完成")
                _emit_finished_once(result)
            except Exception as e:
                logger.error("AI generation failed: %s", e)
                if not _finished_flag[0]:
                    self.step_changed.emit("failed", "生成失败")
                _emit_finished_once({
                    "title": f"[Error] {e}",
                    "content": "",
                    "tags": "",
                    "images": [],
                    "product_name": product.get("title", ""),
                    "posts": [],
                    "directions": [],
                    "errors": [str(e)],
                })

        _done = threading.Event()

        def _run_wrapper():
            try:
                _run()
            finally:
                # Safety reset in case _emit_finished_once was not called
                with self._finished_lock:
                    if not _finished_flag[0]:
                        self._is_generating = False
                _done.set()

        threading.Thread(target=_run_wrapper, daemon=True, name="ai-generate").start()

        # 超时看门狗：500 秒未完成则通知 UI
        def _watchdog():
            if not _done.wait(timeout=500):
                logger.warning("AI generation timed out after 500s")
                self.step_changed.emit("failed", "生成超时（500s）")
                _emit_finished_once({
                    "title": "[Timeout] 生成超时",
                    "content": "",
                    "tags": "",
                    "images": [],
                    "product_name": product.get("title", ""),
                    "posts": [],
                    "directions": [],
                    "errors": ["生成超过 300 秒未完成，请检查网络连接后重试。"],
                })

        threading.Thread(target=_watchdog, daemon=True, name="ai-watchdog").start()

    def retry_images(self, product, style_indices: list[int], existing_images: list[str]):
        _done = threading.Event()
        _emit_lock = threading.Lock()
        _emitted = [False]

        def _emit_retry_done(payload):
            with _emit_lock:
                if _emitted[0]:
                    return
                _emitted[0] = True
            self.image_retry_done.emit(payload)

        def _run():
            product_name = product.get("title", "")
            errors = []
            image_results = []
            images = []
            try:
                from src.ai.image_generator import check_kimi_health, generate_images, kimi_health_message
                if not check_kimi_health():
                    errors.append(kimi_health_message(start_if_needed=True))
                else:
                    product_img = _resolve_product_image(product)
                    if product_img:
                        logger.info("重试生图参考图: %s", product_img)
                    else:
                        logger.warning("无参考图，将使用纯文字生图")
                    output_dir = _reuse_or_create_image_output_dir(product_name, existing_images)
                    img_result = generate_images(
                        product_name=product_name,
                        output_dir=output_dir,
                        product_image_path=product_img,
                        count=3,
                        style_indices=style_indices,
                        product_context=_product_image_context(product),
                    )
                    images = img_result.images
                    image_results = img_result.results
                    if not images:
                        detail = _image_error_summary(image_results)
                        errors.append(f"缺失图片重试失败：{detail}" if detail else "缺失图片重试失败，请检查 ChatGPT 登录状态")
            except Exception as e:
                errors.append(f"缺失图片重试失败: {e}")
                logger.warning("Image retry failed: %s", e)

            try:
                seen = {
                    item.get("index")
                    for item in image_results
                    if isinstance(item, dict)
                }
                for index in style_indices:
                    if index not in seen:
                        image_results.append({
                            "index": index,
                            "status": "failed",
                            "path": "",
                            "error": "；".join(errors) if errors else "生成失败或超时，请重试",
                        })

                _emit_retry_done({
                    "images": images,
                    "image_results": image_results,
                    "warnings": errors,
                })
            except Exception as e:
                logger.error("retry_images post-processing failed: %s", e)
                _emit_retry_done({
                    "images": images,
                    "image_results": [],
                    "warnings": errors + [f"内部错误: {e}"],
                })
            finally:
                _done.set()

        threading.Thread(target=_run, daemon=True, name="img-retry").start()

        def _watchdog():
            if not _done.wait(timeout=450):
                logger.warning("retry_images timed out after 450s")
                _emit_retry_done({
                    "images": [],
                    "image_results": [],
                    "warnings": ["图片重试超过 450 秒未完成，请检查网络后重试。"],
                })

        threading.Thread(target=_watchdog, daemon=True, name="img-retry-watchdog").start()

    def generate_note_images(self, item: dict, product: dict | None = None):
        _done = threading.Event()
        _emit_lock = threading.Lock()
        _emitted = [False]

        def _emit_note_done(payload):
            with _emit_lock:
                if _emitted[0]:
                    return
                _emitted[0] = True
            self.note_image_done.emit(payload)

        def _run():
            note_id = item.get("id")
            product_name = (
                (product or {}).get("title")
                or item.get("product_name")
                or item.get("title")
                or "商品"
            )
            existing_images = [
                path for path in item.get("images", [])
                if path and os.path.exists(path)
            ]
            errors = []
            image_results = []
            images = []

            try:
                from src.ai.image_generator import check_kimi_health, generate_images, kimi_health_message
                if not check_kimi_health():
                    errors.append(kimi_health_message(start_if_needed=True))
                else:
                    # 优先级: local_images > main_images URL下载 > existing_images
                    product_img = _resolve_product_image(product)
                    if not product_img and existing_images:
                        product_img = existing_images[0]
                    if product_img:
                        logger.info("笔记生图参考图: %s", product_img)
                    else:
                        errors.append("未找到采集产品图，将使用文字提示词直接生图")

                    base_prompt = item.get("image_prompt") or (
                        f"请为 {product_name} 生成适合小红书种草笔记的真实商品图片。"
                    )
                    from src.ai.prompt_templates import get_all_image_prompts
                    image_context = _product_image_context(
                        product,
                        extra="\n".join([
                            f"用户图片提示词: {base_prompt}",
                            f"笔记标题: {item.get('title', '')}",
                            f"笔记正文片段: {(item.get('content') or '')[:500]}",
                        ]),
                    )
                    prompt_overrides = get_all_image_prompts(product_name, product_context=image_context)

                    if len(existing_images) < 3:
                        style_indices = list(range(len(existing_images), 3))
                    else:
                        style_indices = [0, 1, 2]

                    output_dir = _new_image_output_dir(product_name)
                    img_result = generate_images(
                        product_name=product_name,
                        output_dir=output_dir,
                        product_image_path=product_img,
                        count=3,
                        style_indices=style_indices,
                        prompt_overrides=prompt_overrides,
                        product_context=image_context,
                    )
                    images = img_result.images
                    image_results = img_result.results
                    if not images:
                        detail = _image_error_summary(image_results)
                        errors.append(f"直接生成图片失败：{detail}" if detail else "直接生成图片失败，请检查 ChatGPT 登录状态")
            except Exception as e:
                errors.append(f"直接生成图片失败: {e}")
                logger.warning("Note image generation failed: %s", e)

            try:
                all_images = existing_images + images
                _emit_note_done({
                    "note_id": note_id,
                    "product_name": product_name,
                    "images": images,
                    "all_images": all_images,
                    "image_results": image_results,
                    "warnings": errors,
                })
            except Exception as e:
                logger.error("generate_note_images post-processing failed: %s", e)
                _emit_note_done({
                    "note_id": note_id,
                    "product_name": product_name,
                    "images": [],
                    "all_images": existing_images,
                    "image_results": [],
                    "warnings": errors + [f"内部错误: {e}"],
                })
            finally:
                _done.set()

        threading.Thread(target=_run, daemon=True, name="note-img").start()

        def _watchdog():
            if not _done.wait(timeout=450):
                logger.warning("generate_note_images timed out after 450s")
                _emit_note_done({
                    "note_id": item.get("id"),
                    "product_name": (product or {}).get("title") or item.get("title") or "商品",
                    "images": [],
                    "all_images": [p for p in item.get("images", []) if p and os.path.exists(p)],
                    "image_results": [],
                    "warnings": ["直接生成图片超过 450 秒未完成，请检查网络后重试。"],
                })

        threading.Thread(target=_watchdog, daemon=True, name="note-img-watchdog").start()

    def regenerate_content(self, product, direction_data: dict, style="种草", provider=None, model=None, content_template=""):
        """仅重新生成某个方向的文案（3 篇），保留图片"""
        def _run():
            from src.ai.api_key_manager import get_key_manager, Provider as KMProvider

            product_name = product.get("title", "")
            desc = product.get("description", "") or product_name
            price = str(product.get("price", "")) or "未知"
            selling_points = _extract_selling_points(product)

            llm_provider = None
            if provider:
                try:
                    llm_provider = KMProvider(provider)
                except ValueError:
                    pass

            self.step_changed.emit("content_generating", f"重新生成文案：{direction_data.get('name', '')}")

            try:
                from src.ai.content_generator import generate_direction_content
                dir_content = generate_direction_content(
                    product_name=product_name,
                    description=desc,
                    price=price,
                    selling_points=selling_points,
                    direction=direction_data,
                    style=style,
                    provider=llm_provider,
                    content_template=content_template or "",
                    search_results=getattr(self, '_search_results', '') or "",
                )
                new_posts = []
                for post in dir_content.posts:
                    new_posts.append({
                        "direction_id": direction_data["id"],
                        "direction_name": direction_data["name"],
                        "hook_style": post.hook_style,
                        "title": post.title,
                        "content": post.content,
                        "tags": " ".join(post.tags) if post.tags else "",
                    })
                self.step_changed.emit("completed", "文案重新生成完成")
                self.content_regenerated.emit({
                    "direction_id": direction_data["id"],
                    "direction_name": direction_data["name"],
                    "posts": new_posts,
                })
            except Exception as e:
                logger.error("Regenerate content failed: %s", e)
                self.step_changed.emit("failed", f"文案重新生成失败: {e}")
                self.content_regenerated.emit({
                    "direction_id": direction_data["id"],
                    "direction_name": direction_data["name"],
                    "posts": [],
                    "error": str(e),
                })

        threading.Thread(target=_run, daemon=True, name="regen-content").start()

    def regenerate_images(self, product, existing_images: list):
        """重新生成商品图片，保留文案"""
        def _run():
            product_name = product.get("title", "")

            self.step_changed.emit("image_generating", "重新生成图片")

            errors = []
            image_results = []
            images = []
            try:
                from src.ai.image_generator import check_kimi_health, generate_images, kimi_health_message
                if not check_kimi_health():
                    errors.append(kimi_health_message(start_if_needed=True))
                else:
                    product_img = _resolve_product_image(product)
                    if product_img:
                        logger.info("重新生图参考图: %s", product_img)
                    else:
                        logger.warning("无参考图，将使用纯文字生图")
                    output_dir = _new_image_output_dir(product_name)
                    img_result = generate_images(
                        product_name=product_name,
                        output_dir=output_dir,
                        product_image_path=product_img,
                        count=3,
                        product_context=_product_image_context(product),
                    )
                    images = img_result.images
                    image_results = img_result.results
                    if not images:
                        detail = _image_error_summary(image_results)
                        errors.append(f"图片重新生成失败：{detail}" if detail else "图片重新生成失败，请检查 ChatGPT 登录状态")
            except Exception as e:
                errors.append(f"图片重新生成失败: {e}")
                logger.warning("Image regeneration failed: %s", e)

            self.step_changed.emit("completed", "图片重新生成完成")
            self.images_regenerated.emit({
                "images": list(images),
                "image_results": list(image_results),
                "warnings": errors,
            })

        threading.Thread(target=_run, daemon=True, name="regen-images").start()
