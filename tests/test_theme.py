"""界面主题（黑白双主题）测试。

覆盖：
- 主题解析（默认浅色 / 覆盖）；
- 主题应用（dark 使 Window 色变深、light 恢复平台默认浅色）；
- 支持的主题选项清单。
"""

import os

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.theme import (
    DEFAULT_UI_THEME,
    SUPPORTED_THEMES,
    UI_STYLE_NAME,
    apply_ui_style,
    apply_ui_theme,
    resolve_ui_theme,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _window_color(app: QApplication) -> QColor:
    return app.palette().color(QPalette.ColorRole.Window)


def test_resolve_ui_theme_default():
    assert resolve_ui_theme() == DEFAULT_UI_THEME
    assert resolve_ui_theme(None) == DEFAULT_UI_THEME


def test_resolve_ui_theme_override():
    assert resolve_ui_theme("dark") == "dark"
    assert resolve_ui_theme("") == DEFAULT_UI_THEME


def test_supported_themes():
    assert SUPPORTED_THEMES == [("Light", "light"), ("Dark", "dark")]


def test_apply_ui_theme_dark(qapp):
    """深色主题：Window 色变深（官方 dark palette 深灰 #353535）。"""
    assert apply_ui_theme("dark") == "dark"
    assert _window_color(qapp) == QColor(53, 53, 53)


def test_apply_ui_theme_light_restores_default(qapp):
    """浅色主题：先切深色再切浅色，恢复平台默认浅色调色板。"""
    apply_ui_theme("dark")
    assert apply_ui_theme("light") == "light"
    expected = qapp.style().standardPalette().color(QPalette.ColorRole.Window)
    assert _window_color(qapp) == expected


def test_apply_ui_theme_default_light(qapp):
    assert apply_ui_theme() == DEFAULT_UI_THEME
    assert _window_color(qapp) == qapp.style().standardPalette().color(
        QPalette.ColorRole.Window
    )


def test_apply_ui_style_sets_fusion(qapp):
    """固定为 Fusion 样式：调色板驱动的主题需样式逐角色遵循 QPalette。

    先切到原生 ``windowsvista`` 样式，再调用 :func:`apply_ui_style`，
    断言被切回 Fusion（回归：Windows 原生样式忽略应用调色板，深色不生效）。
    """
    qapp.setStyle("windowsvista")
    apply_ui_style()
    assert qapp.style().objectName().lower() == UI_STYLE_NAME.lower()


def test_apply_ui_theme_applies_fusion_style(qapp):
    """应用主题时一并确保 Fusion 样式生效（与样式名无关的入口路径也覆盖）。"""
    qapp.setStyle("windowsvista")
    apply_ui_theme("dark")
    assert qapp.style().objectName().lower() == UI_STYLE_NAME.lower()
