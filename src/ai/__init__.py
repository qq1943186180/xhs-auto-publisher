"""
小红书 AI 内容生成模块
"""

from .title_generator import generate_titles, TitleResult
from .content_generator import generate_content, generate_tags, ContentResult, generate_direction_content, DirectionPost, DirectionContentResult
from .direction_generator import generate_directions, Direction, DirectionResult
from .image_generator import generate_images, ImageResult
from .api_key_manager import get_key_manager, APIKeyManager, Provider
from .llm_client import call_llm, extract_json, AuthenticationError, RateLimitError, NetworkError
from .text_cleaner import soften_title, soften_ai_style, soften_story_title

__all__ = [
    # Title
    "generate_titles",
    "TitleResult",
    # Content
    "generate_content",
    "generate_tags",
    "ContentResult",
    "generate_direction_content",
    "DirectionPost",
    "DirectionContentResult",
    # Direction
    "generate_directions",
    "Direction",
    "DirectionResult",
    # Image
    "generate_images",
    "ImageResult",
    # API Key
    "get_key_manager",
    "APIKeyManager",
    "Provider",
    # LLM Client
    "call_llm",
    "extract_json",
    "AuthenticationError",
    "RateLimitError",
    "NetworkError",
    # Text Cleaner
    "soften_title",
    "soften_ai_style",
    "soften_story_title",
]
