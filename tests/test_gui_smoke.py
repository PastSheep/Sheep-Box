"""GUI 无头冒烟测试（QT_QPA_PLATFORM=offscreen）。

验证主窗口能实例化、含"设置"标签页，且设置表单保存能写回配置。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTabWidget

from gui.controller.settings_controller import SettingsController
from gui.view.main_window import MainWindow
from gui.view.settings_tab import SettingsTab


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_hosts_settings_tab(qapp, config_manager):
    win = MainWindow(SettingsController(config_manager))
    tabs = win.centralWidget()
    assert isinstance(tabs, QTabWidget)
    assert tabs.count() == 1
    assert isinstance(tabs.widget(0), SettingsTab)
    assert tabs.tabText(0) == "设置"
    win.close()


def test_settings_tab_loads_and_saves(qapp, config_manager):
    controller = SettingsController(config_manager)
    tab = SettingsTab(controller)
    # 修改表单并触发"保存并重载"
    tab._mode_combo.setCurrentText("medium")
    tab._gpu_check.setChecked(False)
    tab._save_btn.click()
    reloaded = controller.load()
    assert reloaded["mode"] == "medium"
    assert reloaded["gpu_enabled"] is False
    # 状态标签应显示成功文案
    assert "已保存并重载" in tab._status_label.text()
    tab.close()


def test_settings_tab_restore_defaults(qapp, config_manager):
    controller = SettingsController(config_manager)
    controller.save(
        {
            "mode": "all",
            "default_spec": "tiny",
            "gpu_enabled": False,
            "text_score": 0.9,
            "box_thresh": 0.9,
            "unclip_ratio": 3.0,
            "language": "ja",
        }
    )
    tab = SettingsTab(controller)
    tab._restore_btn.click()
    v = controller.load()
    assert v["mode"] == "small"
    assert v["default_spec"] == "small"
    assert v["gpu_enabled"] is True
    assert v["text_score"] == 0.5
    tab.close()
