"""GUI 无头冒烟测试（QT_QPA_PLATFORM=offscreen）。

验证主窗口能实例化、含"设置"标签页（当前为占位页，不承载 OCR 配置）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QTabWidget

from gui.view.main_window import MainWindow
from gui.view.settings_tab import SettingsTab


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_hosts_settings_tab(qapp):
    win = MainWindow()
    tabs = win.centralWidget()
    assert isinstance(tabs, QTabWidget)
    assert tabs.count() == 1
    assert isinstance(tabs.widget(0), SettingsTab)
    win.close()


def test_settings_tab_is_placeholder(qapp):
    """设置页当前为占位：只显示占位说明文字，不承载 OCR 配置表单。"""
    tab = SettingsTab()
    assert tab.findChild(QLabel) is not None
    tab.close()


def test_settings_tab_has_language_combo(qapp):
    """设置页承载界面语言下拉（zh_CN / en 两个选项）。"""
    tab = SettingsTab()
    combo = tab.findChild(QComboBox)
    assert combo is not None
    assert combo.findData("zh_CN") >= 0
    assert combo.findData("en") >= 0
    tab.close()
