"""设计系统测试：令牌、样式生成、背景层与模糊工具。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget

from gui.theme.background import BackgroundWidget
from gui.theme.blur import blur_image
from gui.theme.style import build_popup_stylesheet, build_stylesheet, rgba
from gui.theme.tokens import DARK, LIGHT, TOKENS, tokens_for


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_rgba_converts_hex_and_alpha():
    assert rgba("#0F172A", 0.14) == "rgba(15,23,42,14%)"
    assert rgba("#FFFFFF", 1.0) == "rgba(255,255,255,100%)"


def test_rgba_handles_invalid_input():
    assert rgba("not-a-color", 1.0) == "rgba(0,0,0,100%)"


def test_rgba_clamps_alpha():
    assert rgba("#FFFFFF", 1.7) == "rgba(255,255,255,100%)"
    assert rgba("#FFFFFF", -0.5) == "rgba(255,255,255,0%)"


def test_tokens_for_known_and_fallback():
    assert tokens_for("dark") is DARK
    assert tokens_for("light") is LIGHT
    assert tokens_for(None) is LIGHT
    assert tokens_for("unknown") is LIGHT


def test_theme_tokens_share_metrics():
    """深浅两套只有配色不同，尺寸令牌必须一致，避免换主题导致布局跳动。"""
    assert LIGHT.metrics == DARK.metrics
    assert TOKENS == {"light": LIGHT, "dark": DARK}


def test_stylesheet_uses_theme_colors():
    light = build_stylesheet(LIGHT)
    dark = build_stylesheet(DARK)
    assert LIGHT.palette.text_primary in light
    assert DARK.palette.text_primary in dark
    assert "QComboBox:focus" in light
    assert LIGHT.palette.accent in light


def test_popup_stylesheet_uses_menu_tokens():
    """弹层样式由控件单独下发，必须带上菜单色与圆角令牌。"""
    light = build_popup_stylesheet(LIGHT)
    dark = build_popup_stylesheet(DARK)
    assert LIGHT.palette.menu_fill in light
    assert DARK.palette.menu_fill in dark
    assert f"border-radius: {LIGHT.metrics.radius_menu}px" in light
    assert "#ComboPopupView::item:selected" in light


def test_select_combo_popup_uses_tokens(qapp):
    """下拉框弹层：view 带对象名与专属样式，选项高度取令牌，主题切换后重建。"""
    from PySide6.QtWidgets import QStyleOptionViewItem

    from gui.components.select_combo import POPUP_VIEW_NAME, SelectComboBox

    combo = SelectComboBox(LIGHT)
    combo.addItems(["a", "b"])
    view = combo.view()
    assert view.objectName() == POPUP_VIEW_NAME
    assert LIGHT.palette.menu_fill in view.styleSheet()

    delegate = view.itemDelegate()
    size = delegate.sizeHint(QStyleOptionViewItem(), view.model().index(0, 0))
    assert size.height() == LIGHT.metrics.menu_item_height

    combo.set_tokens(DARK)
    assert DARK.palette.menu_fill in view.styleSheet()


def test_blur_image_keeps_size(qapp):
    source = QImage(80, 60, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("#2F6FEB"))
    result = blur_image(source, 12.0)
    assert result.size() == source.size()
    assert not result.isNull()


def test_blur_image_zero_radius_returns_input(qapp):
    source = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("#000000"))
    assert blur_image(source, 0.0) is source


def test_backdrop_matches_widget_geometry(qapp):
    background = BackgroundWidget(LIGHT)
    background.resize(400, 300)
    child = QWidget(background)
    child.setGeometry(20, 30, 200, 100)
    image = background.backdrop_for(child)
    assert image is not None
    assert image.size() == child.size()


def test_backdrop_clipped_outside(qapp):
    """控件超出背景范围时，取图被裁剪，不会返回超尺寸图像。"""
    background = BackgroundWidget(LIGHT)
    background.resize(200, 150)
    child = QWidget(background)
    child.setGeometry(150, 100, 200, 120)
    image = background.backdrop_for(child)
    assert image is not None
    assert image.width() <= 50
    assert image.height() <= 50


def test_set_image_switches_background(qapp, tmp_path):
    """设置图片背景后背景版本自增（卡片缓存随之失效）。"""
    background = BackgroundWidget(LIGHT)
    background.resize(300, 200)
    version_before = background.version()
    image_path = tmp_path / "bg.png"
    image = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#7A8CA8"))
    assert image.save(str(image_path))
    background.set_image(str(image_path))
    assert background.version() > version_before
    assert background.backdrop_for(background) is not None
