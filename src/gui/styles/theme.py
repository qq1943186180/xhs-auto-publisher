"""
XHS Auto Publisher - Theme & Style (PyQt-Fluent-Widgets)
Supports Light and Dark themes
"""
from qfluentwidgets import setTheme, Theme, setThemeColor

# === Color Constants ===
PRIMARY = "#ff2442"
PRIMARY_HOVER = "#e61f3a"
PRIMARY_LIGHT = "#fff1f3"

APP_BACKGROUND = "#f7f8fa"
SURFACE = "#ffffff"
SURFACE_ALT = "#f9fafb"
BORDER = "#e5e7eb"
BG_CARD = SURFACE_ALT

TEXT_PRIMARY = "#111827"
TEXT_SECONDARY = "#4b5563"
TEXT_MUTED = "#8a8f98"

SUCCESS = "#16a34a"
WARNING = "#d97706"
ERROR = "#dc2626"
INFO = "#2563eb"

RADIUS_SM = "6px"
RADIUS_MD = "8px"

# Dark mode overrides
_DARK_APP_BACKGROUND = "#1e1e2e"
_DARK_SURFACE = "#282840"
_DARK_SURFACE_ALT = "#2d2d44"
_DARK_BORDER = "#3d3d5c"
_DARK_TEXT_PRIMARY = "#e0e0e0"
_DARK_TEXT_SECONDARY = "#a0a0b0"
_DARK_TEXT_MUTED = "#6c6c80"


_current_theme = "light"


def setup_theme(theme: str = "light"):
    """Setup theme with XHS red accent.

    Args:
        theme: "light" or "dark"
    """
    global _current_theme, APP_BACKGROUND, SURFACE, SURFACE_ALT, BORDER, BG_CARD
    global TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED

    _current_theme = theme.lower()

    if _current_theme == "dark":
        setTheme(Theme.DARK)
        APP_BACKGROUND = _DARK_APP_BACKGROUND
        SURFACE = _DARK_SURFACE
        SURFACE_ALT = _DARK_SURFACE_ALT
        BORDER = _DARK_BORDER
        BG_CARD = _DARK_SURFACE_ALT
        TEXT_PRIMARY = _DARK_TEXT_PRIMARY
        TEXT_SECONDARY = _DARK_TEXT_SECONDARY
        TEXT_MUTED = _DARK_TEXT_MUTED
    else:
        setTheme(Theme.LIGHT)
        APP_BACKGROUND = "#f7f8fa"
        SURFACE = "#ffffff"
        SURFACE_ALT = "#f9fafb"
        BORDER = "#e5e7eb"
        BG_CARD = "#f9fafb"
        TEXT_PRIMARY = "#111827"
        TEXT_SECONDARY = "#4b5563"
        TEXT_MUTED = "#8a8f98"

    setThemeColor(PRIMARY)


def get_current_theme() -> str:
    """获取当前主题名"""
    return _current_theme


def page_title_style() -> str:
    return f"font-size: 24px; font-weight: 700; color: {TEXT_PRIMARY};"


def page_subtitle_style() -> str:
    return f"font-size: 13px; color: {TEXT_SECONDARY};"


def section_title_style() -> str:
    return f"font-size: 16px; font-weight: 700; color: {TEXT_PRIMARY};"


def muted_text_style(size: int = 13) -> str:
    return f"font-size: {size}px; color: {TEXT_MUTED};"


def panel_style() -> str:
    return f"""
        QWidget {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_MD};
        }}
    """


def placeholder_style() -> str:
    return f"""
        QLabel {{
            background: {SURFACE_ALT};
            border: 1px dashed {BORDER};
            border-radius: {RADIUS_MD};
            color: {TEXT_MUTED};
            font-size: 13px;
        }}
    """


def image_tile_style(border_color: str = BORDER) -> str:
    return f"""
        QWidget {{
            background: {SURFACE_ALT};
            border: 1px solid {border_color};
            border-radius: {RADIUS_MD};
        }}
        QWidget:hover {{
            border-color: {PRIMARY};
        }}
    """


def danger_button_style() -> str:
    return f"""
        QPushButton {{
            color: {ERROR};
            font-weight: 600;
        }}
        QPushButton:hover {{
            color: #ffffff;
            background: {ERROR};
        }}
    """
