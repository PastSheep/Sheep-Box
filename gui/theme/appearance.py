"""应用界面外观：Fusion 样式 + 调色板 + 令牌生成的 QSS。

与 :mod:`app.theme` 的分工：
- :mod:`app.theme` 只管样式固定与 ``QPalette``（与具体视觉风格无关）；
- 本模块在它之上叠加设计令牌生成的 QSS（控件圆角、边框、字号等形态），
  形成 GUI 的完整外观。

为什么仍要 Fusion：Windows 原生 ``windowsvista`` 样式不读取应用调色板，
深色主题会失效；QSS 也以 Fusion 为基底才能稳定绘制控件。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication

from app.theme import apply_ui_theme
from gui.theme.style import build_stylesheet
from gui.theme.tokens import DesignTokens, tokens_for

logger = logging.getLogger(__name__)

__all__ = ["apply_appearance"]


def apply_appearance(theme: str | None = None) -> DesignTokens:
    """应用界面外观（主题调色板 + 控件样式），返回生效的设计令牌。

    Args:
        theme: 主题值（``light`` / ``dark``）；缺省浅色。

    Returns:
        当前生效的设计令牌，可直接交给组件使用。
    """
    resolved = apply_ui_theme(theme)
    tokens = tokens_for(resolved)

    app = QApplication.instance()
    if isinstance(app, QApplication):
        app.setStyleSheet(build_stylesheet(tokens))
    else:
        logger.debug("无 QApplication 实例，跳过样式表应用")
    return tokens
