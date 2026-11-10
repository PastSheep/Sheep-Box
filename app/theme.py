"""界面主题（黑白双主题）骨架。

首版实现浅色/深色双主题：通过 ``QApplication.setPalette`` 应用主题调色板
（深色配色为 Qt 官方 dark palette 标准做法）。``setPalette`` 触发全部控件
重绘、跨平台一致，且可在测试（offscreen）中断言，效果确定。调色板角色需由
``Fusion`` 样式逐角色遵循（见 :data:`UI_STYLE_NAME`），故应用主题前先固定该样式。

主题调色板颜色集中在本模块定义（主题本身即需要配色），设置界面布局不硬编码
颜色（用 ``QGroupBox`` / ``QPalette`` 自动适配）。未来如需「跟随系统」、
自定义配色或 QSS，在此基础上扩展。

注意：本模块顶层不导入 PySide6，保持 ``import app.theme`` 轻量；
``Qt`` / ``QApplication`` / ``QPalette`` 在函数内延迟导入。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config.schema import Theme

if TYPE_CHECKING:
    from PySide6.QtGui import QPalette

logger = logging.getLogger(__name__)

DEFAULT_UI_THEME = Theme.LIGHT.value

#: 界面所使用的 Qt 样式名。主题配色完全基于 ``QPalette`` 角色，而 Windows
#: 默认的 ``windowsvista`` 原生样式按系统主题绘制控件、不读取应用调色板，
#: 会导致深色主题下大部分控件仍是浅色。``Fusion`` 样式逐角色遵循调色板，
#: 是 Qt 官方 dark palette 方案所依赖的样式，故统一固定为 Fusion。
UI_STYLE_NAME = "Fusion"

#: 支持的界面主题选项（显示名, 主题值）。显示名在界面层经 ``tr()`` 翻译。
SUPPORTED_THEMES: list[tuple[str, str]] = [
    ("Light", Theme.LIGHT.value),
    ("Dark", Theme.DARK.value),
]


def apply_ui_style() -> None:
    """固定应用 Qt 样式为 :data:`UI_STYLE_NAME`（须在 ``QApplication`` 创建后调用）。

    调色板驱动的黑白主题依赖样式逐角色读取 ``QPalette``；不固定样式时，
    Windows 原生 ``windowsvista`` 样式会忽略应用调色板，使深色主题不生效。
    无 ``QApplication`` 实例（如无头/测试）时安全跳过。
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if isinstance(app, QApplication) and (
        app.style().objectName().lower() != UI_STYLE_NAME.lower()
    ):
        app.setStyle(UI_STYLE_NAME)
        logger.info("界面样式已应用: %s", UI_STYLE_NAME)


def resolve_ui_theme(config_theme: str | None = None) -> str:
    """解析界面主题：优先取传入的配置值，缺省浅色。

    Args:
        config_theme: 配置文件中的界面主题（``app.theme``）。

    Returns:
        生效的界面主题。
    """
    return config_theme if config_theme else DEFAULT_UI_THEME


def apply_ui_theme(theme: str | None = None) -> str:
    """应用界面主题（须在 ``QApplication`` 创建后调用；无实例时安全跳过）。

    Args:
        theme: 界面主题（``light`` / ``dark``）；缺省浅色。

    Returns:
        实际生效的主题值。
    """
    from PySide6.QtWidgets import QApplication

    resolved = resolve_ui_theme(theme)
    apply_ui_style()
    app = QApplication.instance()
    if isinstance(app, QApplication):
        if resolved == Theme.DARK.value:
            app.setPalette(_dark_palette())
        else:
            # 恢复平台默认（浅色）调色板
            app.setPalette(app.style().standardPalette())
    logger.info("界面主题已应用: %s", resolved)
    return resolved


def _dark_palette() -> QPalette:
    """构建深色主题调色板（Qt 官方 dark palette 配色）。

    Returns:
        深色 ``QPalette``。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette

    window = QColor(53, 53, 53)
    base = QColor(25, 25, 25)
    text = QColor(210, 210, 210)
    highlight = QColor(42, 130, 218)
    disabled_text = QColor(127, 127, 127)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, window)
    palette.setColor(QPalette.ColorRole.ToolTipBase, text)
    palette.setColor(QPalette.ColorRole.ToolTipText, window)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, disabled_text)
    palette.setColor(QPalette.ColorRole.Button, window)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, highlight)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text
    )
    return palette
