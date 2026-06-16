"""
XHS Auto Publisher - Theme & Style (PyQt-Fluent-Widgets)
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


def setup_theme():
    """Setup light theme with XHS red accent."""
    setTheme(Theme.LIGHT)
    setThemeColor(PRIMARY)


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
