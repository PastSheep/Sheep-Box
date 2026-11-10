"""设计令牌（Design Tokens）：中性现代风格的两套取值（浅色 / 深色）。

界面所有颜色、间距、字号、圆角、控件尺寸与玻璃参数都集中在此，组件只读取
令牌、不硬编码数值。换主题或微调风格只改这里的值，页面代码无需改动；后续
新增页面直接复用同一套令牌即可保持一致。

约定：
- 颜色用 ``#RRGGBB``，透明度单列成 ``*_alpha``，由 :mod:`gui.theme.style`
  拼成 QSS 需要的 ``rgba(...)``，QPainter 侧用 ``QColor.setAlphaF``；
- 尺寸走 8pt 网格（4 / 8 / 12 / 16 / 24 / 32），字号四档（11 / 12 / 16 / 24）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Palette:
    """界面配色（不透明色 ``#RRGGBB`` + 单独透明度）。"""

    bg_base: str
    bg_gradient_end: str
    image_scrim_alpha: float
    glow_primary: str
    glow_primary_alpha: float
    glow_secondary: str
    glow_secondary_alpha: float
    card_fill: str
    card_fill_alpha: float
    card_border: str
    card_border_alpha: float
    card_highlight_alpha: float
    field_fill: str
    field_fill_alpha: float
    field_hover_alpha: float
    field_border: str
    field_border_alpha: float
    menu_fill: str
    menu_border: str
    menu_border_alpha: float
    menu_hover_alpha: float
    menu_selected_alpha: float
    nav_active_alpha: float
    nav_hover_alpha: float
    nav_border_alpha: float
    nav_fill_alpha: float
    nav_highlight_alpha: float
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_ring_alpha: float
    divider: str
    divider_alpha: float
    shadow: str
    shadow_alpha: float


@dataclass(frozen=True)
class Metrics:
    """尺寸与排版令牌。"""

    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 12
    space_lg: int = 16
    space_xl: int = 24
    space_2xl: int = 32
    radius_field: int = 8
    radius_card: int = 10
    radius_window: int = 12
    radius_menu: int = 10
    control_height: int = 32
    control_width: int = 160
    label_width: int = 120
    menu_padding: int = 4
    menu_item_height: int = 30
    menu_item_padding: int = 10
    nav_height: int = 32
    nav_gap: int = 4
    nav_padding: int = 4
    nav_icon: int = 16
    nav_item_padding: int = 12
    nav_arrow_width: int = 24
    font_caption: int = 11
    font_body: int = 12
    font_title: int = 24
    glass_blur: float = 18.0
    image_blur: float = 24.0
    glass_highlight_alpha: float = 0.0
    shadow_blur: float = 24.0
    shadow_offset_y: int = 6


@dataclass(frozen=True)
class DesignTokens:
    """一套完整的设计令牌（配色 + 尺寸）。"""

    palette: Palette
    metrics: Metrics = field(default_factory=Metrics)


LIGHT = DesignTokens(
    palette=Palette(
        bg_base="#F8FAFE",
        bg_gradient_end="#E9EEF6",
        image_scrim_alpha=0.45,
        glow_primary="#2F6FEB",
        glow_primary_alpha=0.20,
        glow_secondary="#00A896",
        glow_secondary_alpha=0.16,
        card_fill="#FFFFFF",
        card_fill_alpha=0.58,
        card_border="#FFFFFF",
        card_border_alpha=0.78,
        card_highlight_alpha=0.85,
        field_fill="#FFFFFF",
        field_fill_alpha=0.10,
        field_hover_alpha=0.24,
        field_border="#0F172A",
        field_border_alpha=0.08,
        menu_fill="#FFFFFF",
        menu_border="#0F172A",
        menu_border_alpha=0.12,
        menu_hover_alpha=0.05,
        menu_selected_alpha=0.10,
        nav_active_alpha=0.12,
        nav_hover_alpha=0.05,
        nav_border_alpha=0.16,
        nav_fill_alpha=0.34,
        nav_highlight_alpha=0.30,
        text_primary="#0F172A",
        text_secondary="#55637A",
        text_muted="#8492A6",
        accent="#2F6FEB",
        accent_ring_alpha=0.14,
        divider="#0F172A",
        divider_alpha=0.07,
        shadow="#101828",
        shadow_alpha=0.09,
    )
)

DARK = DesignTokens(
    palette=Palette(
        bg_base="#1A1D22",
        bg_gradient_end="#14171B",
        image_scrim_alpha=0.62,
        glow_primary="#5691FF",
        glow_primary_alpha=0.22,
        glow_secondary="#00BEAA",
        glow_secondary_alpha=0.15,
        card_fill="#FFFFFF",
        card_fill_alpha=0.10,
        card_border="#FFFFFF",
        card_border_alpha=0.12,
        card_highlight_alpha=0.10,
        field_fill="#FFFFFF",
        field_fill_alpha=0.04,
        field_hover_alpha=0.10,
        field_border="#FFFFFF",
        field_border_alpha=0.10,
        menu_fill="#262A31",
        menu_border="#FFFFFF",
        menu_border_alpha=0.16,
        menu_hover_alpha=0.07,
        menu_selected_alpha=0.16,
        nav_active_alpha=0.18,
        nav_hover_alpha=0.08,
        nav_border_alpha=0.16,
        nav_fill_alpha=0.06,
        nav_highlight_alpha=0.05,
        text_primary="#F1F5F9",
        text_secondary="#C9D4E0",
        text_muted="#8C99AA",
        accent="#6EA8FF",
        accent_ring_alpha=0.18,
        divider="#FFFFFF",
        divider_alpha=0.08,
        shadow="#000000",
        shadow_alpha=0.35,
    )
)

#: 按主题值索引的令牌表。
TOKENS: dict[str, DesignTokens] = {"light": LIGHT, "dark": DARK}


def tokens_for(theme: str | None) -> DesignTokens:
    """取指定主题的设计令牌，未知主题回退浅色。

    Args:
        theme: 主题值（``light`` / ``dark``），可为 ``None``。

    Returns:
        对应的设计令牌。
    """
    return TOKENS.get(theme or "light", LIGHT)
