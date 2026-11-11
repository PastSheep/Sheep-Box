"""GUI 无头冒烟测试（QT_QPA_PLATFORM=offscreen）。

验证新结构：主窗口中央为背景层，其上是自绘标题栏（图标 + 标题 + 导航条 +
窗口三键）与页面堆叠区（设置页 / 示例页），页面内用玻璃卡片承载内容；
偏好控件（界面语言 / 主题下拉）仍可访问。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QStackedWidget

from gui.components.glass_card import GlassCard
from gui.components.gradient_stops import GradientStopsControl
from gui.components.nav_bar import NavBar
from gui.components.title_bar import TITLE_HEIGHT, TitleBar
from gui.theme.background import BackgroundWidget
from gui.view.main_window import MainWindow
from gui.view.sample_page import SamplePage
from gui.view.settings_tab import SettingsTab
from gui.view.window_chrome import _unpack_position, native_frame_enabled


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_structure(qapp):
    """主窗口：背景层作中央控件，内部承载设置页与玻璃卡片。"""
    win = MainWindow()
    assert isinstance(win.centralWidget(), BackgroundWidget)
    page = win.findChild(SettingsTab)
    assert page is not None
    assert page.findChild(GlassCard) is not None
    win.close()


def test_title_bar_embeds_nav_and_window_buttons(qapp):
    """标题栏：高度固定，导航条占中间，三个窗口按钮贴右边缘。"""
    win = MainWindow()
    win.resize(600, 480)
    win.show()
    qapp.processEvents()
    bar = win.findChild(TitleBar)
    nav = win.findChild(NavBar)
    assert bar is not None
    assert nav is not None
    assert bar.height() == TITLE_HEIGHT
    # 导航条在标题栏中间，占据除图标/标题与三键之外的大部分宽度
    assert nav.width() > 300
    assert nav.geometry().right() <= bar.width()
    _minimize, _maximize, close = bar.buttons()
    right_edge = close.mapTo(bar, close.rect().topRight()).x()
    assert abs(bar.width() - right_edge - 1) <= 2
    win.close()


def test_drag_region_excludes_nav_and_buttons(qapp):
    """可拖动区只覆盖图标/标题/空白，导航项与窗口按钮不可拖。"""
    win = MainWindow()
    win.resize(600, 480)
    win.show()
    qapp.processEvents()
    bar = win.findChild(TitleBar)
    assert bar is not None
    assert bar.is_drag_region(4, TITLE_HEIGHT // 2) is True
    nav = win.findChild(NavBar)
    assert nav is not None
    center = nav.mapTo(bar, nav.rect().center())
    assert bar.is_drag_region(center.x(), center.y()) is False
    _minimize, _maximize, close = bar.buttons()
    button_center = close.mapTo(bar, close.rect().center())
    assert bar.is_drag_region(button_center.x(), button_center.y()) is False
    win.close()


def test_native_frame_position_unpacking():
    """命中区坐标解析：lParam 里是 16 位有符号值。"""
    assert _unpack_position(0) == (0, 0)
    assert _unpack_position(100 | (200 << 16)) == (100, 200)
    assert _unpack_position(0xFFFF | (0xFFF0 << 16)) == (-1, -16)
    assert native_frame_enabled() in (True, False)


def test_main_window_has_nav_and_stacked_pages(qapp):
    """主窗口有导航条，导航项与堆叠页数量一致，切页同步。"""
    win = MainWindow()
    nav = win.findChild(NavBar)
    stack = win.findChild(QStackedWidget)
    assert nav is not None
    assert stack is not None
    assert nav.count() == 2
    assert stack.count() == 2
    assert isinstance(stack.currentWidget(), SettingsTab)
    assert win.findChild(SamplePage) is not None

    nav.set_current(1, animate=False)
    assert isinstance(stack.currentWidget(), SamplePage)
    win.close()


def test_settings_page_has_language_combo(qapp):
    """设置页承载界面语言下拉（zh_CN / en 两个选项）。"""
    page = SettingsTab()
    combo = page.findChild(QComboBox)
    assert combo is not None
    assert combo.findData("zh_CN") >= 0
    assert combo.findData("en") >= 0
    page.close()


def test_settings_page_has_theme_combo(qapp):
    """设置页承载黑白主题下拉（light / dark）。"""
    page = SettingsTab()
    theme_combo = next(
        (c for c in page.findChildren(QComboBox) if c.findData("light") >= 0), None
    )
    assert theme_combo is not None
    assert theme_combo.findData("dark") >= 0
    page.close()


def test_settings_page_has_status_bar_controls(qapp):
    """设置页承载状态栏刷新间隔与压力着色控件。"""
    from config.schema import StatusBarConfig

    page = SettingsTab(status_bar=StatusBarConfig())
    interval_combo = next(
        (c for c in page.findChildren(QComboBox) if c.findData(1000) >= 0), None
    )
    assert interval_combo is not None, "应有刷新间隔下拉"
    assert page.findChild(GradientStopsControl) is not None, "应有渐变锚点控件"
    page.close()
