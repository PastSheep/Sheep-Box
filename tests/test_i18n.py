"""界面语言（i18n）骨架测试。

覆盖：
- 界面语言解析（默认 zh_CN / 覆盖）；
- QTranslator 加载（zh_CN.qm 存在且可安装）；
- 翻译实际生效（安装 zh_CN 后页面标题 / 偏好标签为中文）；
- Qt 自带 qtbase 翻译生效（取色对话框等内建控件文案跟随语言）；
- 切换到英文后回退源文本。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QColorDialog, QComboBox, QLabel, QPushButton

from app.i18n import (
    I18N_DIR,
    install_ui_translator,
    resolve_ui_language,
    switch_ui_language,
)
from gui.view.main_window import MainWindow
from gui.view.sample_page import SamplePage
from gui.view.settings_tab import SettingsTab


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
    """安装 zh_CN 翻译后，窗口标题 / 页面标题 / 偏好标签应为中文。"""
    assert install_ui_translator("zh_CN") is True
    window = MainWindow()
    page = window.findChild(SettingsTab)
    assert page is not None
    labels = [label.text() for label in page.findChildren(QLabel)]
    assert "外观" in labels
    assert "主题" in labels
    assert "界面语言" in labels
    assert window.windowTitle() == "Sheep Box"
    window.close()


def test_sample_page_translated_to_zh_CN(qapp):
    """示例页标题与说明在 zh_CN 下为中文。"""
    assert install_ui_translator("zh_CN") is True
    window = MainWindow()
    page = window.findChild(SamplePage)
    assert page is not None
    labels = [label.text() for label in page.findChildren(QLabel)]
    assert "示例" in labels
    assert "导航条" in labels
    window.close()


def test_switch_language_updates_ui(qapp):
    """切换到 English 后，界面文本回退英文源（en 无 .qm）。"""
    assert install_ui_translator("zh_CN") is True
    window = MainWindow(config_manager=None)
    page = window.findChild(SettingsTab)
    assert page is not None
    combo = page.findChild(QComboBox)
    assert combo is not None
    assert window.windowTitle() == "Sheep Box"
    combo.setCurrentIndex(combo.findData("en"))
    labels = [label.text() for label in page.findChildren(QLabel)]
    assert window.windowTitle() == "Sheep Box"
    assert "Appearance" in labels
    window.close()


def _color_dialog_button_texts() -> list[str]:
    """构造取色对话框并返回其内建按钮文案（Qt 合成控件，走 qtbase 翻译）。"""
    dialog = QColorDialog()
    dialog.show()
    QApplication.processEvents()
    texts = [button.text() for button in dialog.findChildren(QPushButton)]
    dialog.close()
    return texts


def test_qtbase_translator_localizes_builtin_dialogs(qapp):
    """zh_CN 下 Qt 内建对话框（QColorDialog）的按钮文案应为中文。"""
    assert install_ui_translator("zh_CN") is True
    texts = _color_dialog_button_texts()
    assert "确定" in texts
    assert "取消" in texts


def test_switch_to_en_restores_qt_builtin_english(qapp):
    """切到 en 后 Qt 内建对话框回到英文源，且不影响本程序翻译语义。"""
    assert switch_ui_language("en") is False
    texts = _color_dialog_button_texts()
    assert "OK" in texts
    assert "Cancel" in texts
    assert "确定" not in texts
    assert switch_ui_language("zh_CN") is True
