"""界面语言（i18n）骨架测试。

覆盖：
- 界面语言解析（默认 zh_CN / 覆盖）；
- QTranslator 加载（zh_CN.qm 存在且可安装）；
- 翻译实际生效（安装 zh_CN 后界面文本为中文）；
- 未知语言回退英文源（返回 False）。
"""

import os

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QTabWidget

from app.i18n import I18N_DIR, install_ui_translator, resolve_ui_language
from gui.view.main_window import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_resolve_ui_language_default():
    assert resolve_ui_language() == "zh_CN"
    assert resolve_ui_language(None) == "zh_CN"


def test_resolve_ui_language_override():
    assert resolve_ui_language("en_US") == "en_US"
    assert resolve_ui_language("") == "zh_CN"


def test_zh_CN_translation_file_exists():
    assert I18N_DIR.joinpath("zh_CN.qm").is_file()


def test_install_ui_translator_zh_CN(qapp):
    assert install_ui_translator("zh_CN") is True


def test_install_ui_translator_missing(qapp):
    assert install_ui_translator("xx_XX") is False


def test_ui_text_translated_to_zh_CN(qapp):
    """安装 zh_CN 翻译后，界面标题 / 标签 / tab 文本应为中文。"""
    assert install_ui_translator("zh_CN") is True
    window = MainWindow()
    tabs = window.findChild(QTabWidget)
    assert tabs is not None
    tab0 = tabs.widget(0)
    assert tab0 is not None
    labels = tab0.findChildren(QLabel)
    assert any("暂无可用设置项" in lab.text() for lab in labels)
    assert window.windowTitle() == "Sheep Box 设置"
    assert tabs.tabText(0) == "设置"


def test_switch_language_updates_ui(qapp):
    """切换到 English 后，界面文本回退英文源（en 无 .qm）。"""
    assert install_ui_translator("zh_CN") is True
    window = MainWindow(config_manager=None)
    tabs = window.findChild(QTabWidget)
    assert tabs is not None
    tab0 = tabs.widget(0)
    assert tab0 is not None
    combo = tab0.findChild(QComboBox)
    assert combo is not None
    assert window.windowTitle() == "Sheep Box 设置"
    combo.setCurrentIndex(combo.findData("en"))
    assert window.windowTitle() == "Sheep Box Settings"
    assert tabs.tabText(0) == "Settings"
    window.close()
