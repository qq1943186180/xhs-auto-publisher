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

logger = logging.getLogger(__name__)

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


class AIBackend(QObject):
    """AI generation backend - 两轮生成：方向 → 文案"""
    finished = pyqtSignal(dict)
    direction_done = pyqtSignal(dict)  # 第一轮完成信号
    image_retry_done = pyqtSignal(dict)
    note_image_done = pyqtSignal(dict)

    def generate(self, product, style="种草"):
        def _run():
            try:
                from src.ai.api_key_manager import get_key_manager
                km = get_key_manager()

                product_name = product.get("title", "")
                desc = product_name
                local_imgs = product.get("local_images", [])

                errors = []
                has_llm_key = km.has_keys()

                # ========================================
                # 第一轮：方向生成
                # ========================================
                logger.info("第一轮：生成内容方向...")
                directions_data = []
                if has_llm_key:
                    try:
                        from src.ai.direction_generator import generate_directions
                        dir_result = generate_directions(
                            product_name=product_name,
                            description=desc,
                            style=style,
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
                    from src.ai.direction_generator import _FALLBACK_DIRECTIONS
                    directions_data = list(_FALLBACK_DIRECTIONS)

                # 通知 UI 第一轮完成
                self.direction_done.emit({"directions": directions_data})

                # ========================================
                # 第二轮：每个方向生成 3 篇文案
                # ========================================
                all_posts = []
                for dir_data in directions_data:
                    dir_name = dir_data["name"]
                    logger.info("第二轮：方向「%s」生成 3 篇文案...", dir_name)

                    if has_llm_key:
                        try:
                            from src.ai.content_generator import generate_direction_content
                            dir_content = generate_direction_content(
                                product_name=product_name,
                                description=desc,
                                price="未知",
                                selling_points="",
                                direction=dir_data,
                                style=style,
                            )
                            for post in dir_content.posts:
                                all_posts.append({
                                    "direction_id": dir_data["id"],
                                    "direction_name": dir_name,
                                    "hook_style": post.hook_style,
                                    "title": post.title,
                                    "content": post.content,
                                    "tags": " ".join(post.tags) if post.tags else "",
                                })
                        except Exception as e:
                            errors.append(f"方向「{dir_name}」文案生成失败: {e}")
                            logger.warning("Content gen for direction %s failed: %s", dir_name, e)

                    # 如果该方向没有生成任何帖子，用模板兜底
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
                                "direction_name": dir_name,
                                "hook_style": tp.hook_style,
                                "title": tp.title,
                                "content": tp.content,
                                "tags": " ".join(tp.tags) if tp.tags else "",
                            })

                # 取第一篇的标题作为默认展示
                best_title = all_posts[0]["title"] if all_posts else product_name

                # 生成图片（3 张）
                images = []
                image_results = []
                from src.ai.image_generator import check_kimi_health
                if not check_kimi_health():
                    errors.append("Kimi WebBridge 不可用，请确保浏览器扩展已连接")
                else:
                    try:
                        from src.ai.image_generator import generate_images
                        output_dir = _new_image_output_dir(product_name)
                        product_img = None
                        if local_imgs and os.path.exists(local_imgs[0]):
                            product_img = local_imgs[0]
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
                            errors.append("图片生成失败，请检查 ChatGPT 登录状态")
                        elif len(images) < 3:
                            errors.append(f"图片生成不完整：已生成 {len(images)}/3 张，可点击缺失图片重试")
                    except Exception as e:
                        errors.append(f"图片生成失败: {e}")
                        logger.warning("Image generation failed: %s", e)
                        image_results = []

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

                self.finished.emit(result)
            except Exception as e:
                logger.error("AI generation failed: %s", e)
                self.finished.emit({
                    "title": f"[Error] {e}",
                    "content": "",
                    "tags": "",
                    "images": [],
                    "product_name": product.get("title", ""),
                    "posts": [],
                    "directions": [],
                    "errors": [str(e)],
                })

        threading.Thread(target=_run, daemon=True).start()

    def retry_images(self, product, style_indices: list[int], existing_images: list[str]):
        def _run():
            product_name = product.get("title", "")
            local_imgs = product.get("local_images", [])
            errors = []
            image_results = []
            images = []
            try:
                from src.ai.image_generator import check_kimi_health, generate_images
                if not check_kimi_health():
                    errors.append("Kimi WebBridge 不可用，请确保浏览器扩展已连接")
                else:
                    product_img = None
                    if local_imgs and os.path.exists(local_imgs[0]):
                        product_img = local_imgs[0]
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
                        errors.append("缺失图片重试失败，请检查 ChatGPT 登录状态")
            except Exception as e:
                errors.append(f"缺失图片重试失败: {e}")
                logger.warning("Image retry failed: %s", e)

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

            self.image_retry_done.emit({
                "images": images,
                "image_results": image_results,
                "warnings": errors,
            })

        threading.Thread(target=_run, daemon=True).start()

    def generate_note_images(self, item: dict, product: dict | None = None):
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
                from src.ai.image_generator import check_kimi_health, generate_images
                if not check_kimi_health():
                    errors.append("Kimi WebBridge 不可用，请确保浏览器扩展已连接")
                else:
                    local_imgs = (product or {}).get("local_images", [])
                    product_img = None
                    if local_imgs and os.path.exists(local_imgs[0]):
                        product_img = local_imgs[0]
                    elif existing_images:
                        product_img = existing_images[0]
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
                        errors.append("直接生成图片失败，请检查 ChatGPT 登录状态")
            except Exception as e:
                errors.append(f"直接生成图片失败: {e}")
                logger.warning("Note image generation failed: %s", e)

            all_images = existing_images + images
            self.note_image_done.emit({
                "note_id": note_id,
                "product_name": product_name,
                "images": images,
                "all_images": all_images,
                "image_results": image_results,
                "warnings": errors,
            })

        threading.Thread(target=_run, daemon=True).start()
