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

# Font size constants
FONT_SIZE_PAGE_TITLE = "24px"
FONT_SIZE_SECTION_TITLE = "16px"
FONT_SIZE_BODY = "14px"
FONT_SIZE_SECONDARY = "13px"
FONT_SIZE_CAPTION = "12px"
FONT_SIZE_SMALL = "10px"

# Spacing constants (left, top, right, bottom)
CARD_PADDING_COMPACT = (12, 10, 12, 10)
CARD_PADDING_DEFAULT = (16, 12, 16, 12)
CARD_PADDING_LOOSE = (20, 20, 20, 20)

# Button height constants
BTN_HEIGHT_SM = 28
BTN_HEIGHT_MD = 36
BTN_HEIGHT_LG = 44

# Error background
ERROR_BG = "#fff7f8"

# Text on primary color
TEXT_ON_PRIMARY = "#ffffff"

# Dark mode overrides
_DARK_APP_BACKGROUND = "#1e1e2e"
_DARK_SURFACE = "#282840"
_DARK_SURFACE_ALT = "#2d2d44"
_DARK_BORDER = "#3d3d5c"
_DARK_TEXT_PRIMARY = "#e0e0e0"
_DARK_TEXT_SECONDARY = "#a0a0b0"
_DARK_TEXT_MUTED = "#6c6c80"
_DARK_ERROR_BG = "#2d1f22"
_DARK_PRIMARY_LIGHT = "#3a1520"


_current_theme = "light"


def setup_theme(theme: str = "light"):
    """Setup theme with XHS red accent.

    Args:
        theme: "light" or "dark"
    """
    global _current_theme, APP_BACKGROUND, SURFACE, SURFACE_ALT, BORDER, BG_CARD
    global TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED
    global PRIMARY, PRIMARY_HOVER, PRIMARY_LIGHT, ERROR_BG

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
        ERROR_BG = _DARK_ERROR_BG
        PRIMARY_LIGHT = _DARK_PRIMARY_LIGHT
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
        ERROR_BG = "#fff7f8"
        PRIMARY_LIGHT = "#fff1f3"

    setThemeColor(PRIMARY)


def get_current_theme() -> str:
    """获取当前主题名"""
    return _current_theme


def page_title_style() -> str:
    return f"font-size: {FONT_SIZE_PAGE_TITLE}; font-weight: 700; color: {TEXT_PRIMARY};"


def page_subtitle_style() -> str:
    return f"font-size: {FONT_SIZE_SECONDARY}; color: {TEXT_SECONDARY};"


def section_title_style() -> str:
    return f"font-size: {FONT_SIZE_SECTION_TITLE}; font-weight: 700; color: {TEXT_PRIMARY};"


def dialog_title_style() -> str:
    return f"font-size: 18px; font-weight: 700; color: {TEXT_PRIMARY};"


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
            font-size: {FONT_SIZE_SECONDARY};
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
            color: {TEXT_ON_PRIMARY};
            background: {ERROR};
        }}
    """
