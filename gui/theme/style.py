"""由设计令牌生成 QSS 样式表。

组件形态（输入框圆角、边框、焦点态、字号）统一从令牌生成，保证深浅两套主题
只有颜色不同、结构完全一致。页面布局与玻璃质感由组件自绘，不走 QSS。

注意：QSS 的 ``rgba()`` 透明度用百分比写法，Qt 才能稳定解析。
"""

from __future__ import annotations

import re

from gui.theme.tokens import DesignTokens

__all__ = ["build_stylesheet", "rgba"]

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


def rgba(hex_color: str, alpha: float) -> str:
    """把 ``#RRGGBB`` + 透明度转成 QSS 可解析的 ``rgba(r,g,b,p%)``。

    Args:
        hex_color: 六位十六进制颜色（``#RRGGBB``）。
        alpha: 透明度（0~1）。

    Returns:
        QSS 颜色字符串；非法输入回退为不透明黑。
    """
    match = _HEX_RE.match(hex_color)
    if not match:
        return "rgba(0,0,0,100%)"
    value = match.group(1)
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    percent = max(0, min(100, round(alpha * 100)))
    return f"rgba({red},{green},{blue},{percent}%)"


def build_stylesheet(tokens: DesignTokens) -> str:
    """生成整套控件样式表。

    Args:
        tokens: 当前主题的设计令牌。

    Returns:
        QSS 文本，可直接传给 ``QApplication.setStyleSheet``。
    """
    p = tokens.palette
    m = tokens.metrics
    return f"""
QWidget {{
    color: {p.text_primary};
    font-family: "Segoe UI", "Microsoft YaHei UI", "PingFang SC";
    font-size: {m.font_body}px;
}}
QLabel#PageTitle {{
    font-size: {m.font_title}px;
    font-weight: 600;
    color: {p.text_primary};
}}
QLabel#PageSubtitle {{
    font-size: {m.font_caption}px;
    color: {p.text_secondary};
}}
QLabel#SectionLabel {{
    font-size: {m.font_caption - 1}px;
    color: {p.text_muted};
}}
QLabel#FieldLabel {{
    font-size: {m.font_body}px;
    color: {p.text_primary};
}}
QLabel#BodyText {{
    font-size: {m.font_body}px;
    color: {p.text_secondary};
}}
QLabel#WindowTitle {{
    font-size: {m.font_body}px;
    font-weight: 600;
    color: {p.text_secondary};
}}
QFrame#Divider {{
    background: {rgba(p.divider, p.divider_alpha)};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QComboBox {{
    min-height: {m.control_height - 2}px;
    padding: 0 {m.menu_item_padding + 15}px 0 {m.menu_item_padding + 1}px;
    font-size: {m.font_body}px;
    color: {p.text_primary};
    background: {rgba(p.field_fill, p.field_fill_alpha)};
    border: 1px solid {rgba(p.field_border, p.field_border_alpha)};
    border-radius: {m.radius_field}px;
}}
QComboBox:hover {{
    background: {rgba(p.field_fill, p.field_hover_alpha)};
    border-color: {rgba(p.field_border, min(1.0, p.field_border_alpha + 0.14))};
}}
QComboBox:focus, QComboBox:on {{
    background: {rgba(p.field_fill, p.field_hover_alpha)};
    border: 1px solid {p.accent};
}}
QComboBox::drop-down {{
    border: none;
    width: 0px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
}}
/* 展开态：圆角弹层容器（容器独立设置透明与无边框，见 SelectComboBox）。
   注意这里不用类型选择器：弹层里的 view 是 QComboBoxListView 子类，
   QSS 类型选择器只按类名精确匹配，用 #objectName 最稳。 */
#ComboPopupContainer {{
    background: transparent;
    border: none;
}}
"""


def build_popup_stylesheet(tokens: DesignTokens) -> str:
    """生成下拉弹层样式表。

    弹层是独立的顶层窗口（``QComboBoxPrivateContainer``），应用级样式表对它的
    命中不稳定，因此这段样式由控件直接下发到 ``view`` 上，随主题切换重建。

    Args:
        tokens: 当前主题的设计令牌。

    Returns:
        QSS 文本，可直接传给弹层 ``view`` 的 ``setStyleSheet``。
    """
    p = tokens.palette
    m = tokens.metrics
    return f"""
#ComboPopupView {{
    color: {p.text_primary};
    background: {p.menu_fill};
    border: 1px solid {rgba(p.menu_border, p.menu_border_alpha)};
    border-radius: {m.radius_menu}px;
    outline: none;
    padding: {m.menu_padding}px;
}}
#ComboPopupView::item {{
    padding: 0 {m.menu_item_padding}px;
    border-radius: {m.radius_field}px;
    color: {p.text_primary};
}}
#ComboPopupView::item:hover {{
    background: {rgba(p.menu_border, p.menu_hover_alpha)};
}}
#ComboPopupView::item:selected {{
    background: {rgba(p.accent, p.menu_selected_alpha)};
    color: {p.accent};
}}
"""
