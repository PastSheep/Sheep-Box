"""界面语言（i18n）骨架。

界面文案统一走 Qt 翻译系统（QTranslator + ``.ts/.qm``）：所有 UI 字符串用
``tr()`` 包裹，源语言为英文；提供一个 ``zh_CN`` 翻译（``assets/i18n/``）。
运行时按界面语言加载对应 ``.qm``，未提供翻译的语言回退英文源。后续新增
语言只需增加 ``.ts/.qm`` 并在界面语言选项中登记，无需改动界面代码。

注意：本模块顶层不导入 PySide6，保持 ``import app.i18n`` 轻量；
``QTranslator`` / ``QApplication`` 在函数内延迟导入。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QTranslator

logger = logging.getLogger(__name__)

I18N_DIR = Path(__file__).resolve().parent.parent / "assets" / "i18n"
DEFAULT_UI_LANGUAGE = "zh_CN"

#: 支持的界面语言选项（显示名, 语言代码）。仅 ``zh_CN`` 有编译好的 ``.qm``
#: 翻译；``en`` 作为英文回退源，无需翻译文件。后续新增语言在此追加即可，
#: 界面代码无需改动。
SUPPORTED_UI_LANGUAGES: list[tuple[str, str]] = [
    ("中文", "zh_CN"),
    ("English", "en"),
]

# 持有当前 QTranslator 引用，防止被 GC 回收导致翻译失效（Qt 要求翻译器
# 与应用同生命周期）。
_active_translator: QTranslator | None = None
#: Qt 自带 ``qtbase_<lang>.qm`` 的翻译器（对话框、按钮、右键菜单等内建控件）。
_qtbase_translator: QTranslator | None = None


def resolve_ui_language(config_language: str | None = None) -> str:
    """解析界面语言：优先取传入的配置值，缺省 ``zh_CN``。

    Args:
        config_language: 配置文件中的界面语言（``app.ui_language``）。

    Returns:
        生效的界面语言。
    """
    return config_language if config_language else DEFAULT_UI_LANGUAGE


def install_ui_translator(language: str | None = None) -> bool:
    """加载并安装界面语言翻译（须在 ``QApplication`` 创建后调用）。

    同时安装 Qt 自带的 ``qtbase_<lang>.qm``，让 ``QColorDialog``、
    文件对话框、内建按钮等 Qt 合成控件的文案跟随界面语言。

    Args:
        language: 界面语言（如 ``zh_CN``）；缺省使用 :func:`resolve_ui_language`。

    Returns:
        是否成功安装本程序的翻译；无匹配 ``.qm`` 时回退英文源并返回 ``False``。
    """
    return _apply_language(resolve_ui_language(language), action="安装")


def switch_ui_language(language: str | None = None) -> bool:
    """切换界面语言：移除旧翻译器并安装目标语言翻译。

    Args:
        language: 目标界面语言；缺省使用 :func:`resolve_ui_language`。

    Returns:
        是否成功安装目标语言翻译；无匹配 ``.qm`` 时回退英文源并返回 ``False``。
    """
    return _apply_language(resolve_ui_language(language), action="切换")


def _apply_language(lang: str, *, action: str) -> bool:
    """移除现有翻译器，装目标语言的程序翻译与 Qt 自带翻译。

    Args:
        lang: 目标语言代码。
        action: 日志里描述本次动作的词（安装 / 切换）。

    Returns:
        本程序翻译是否加载成功。
    """
    from PySide6.QtCore import QTranslator
    from PySide6.QtWidgets import QApplication

    global _active_translator, _qtbase_translator
    _remove_translators()

    translator = QTranslator()
    found = translator.load(lang, str(I18N_DIR))
    if found:
        _active_translator = translator
        QApplication.installTranslator(translator)
        logger.info("界面语言已%s: %s", action, lang)
    else:
        logger.info("界面语言%s为 %s（回退英文源）", action, lang)
    _install_qtbase_translator(lang)
    return found


def _remove_translators() -> None:
    """卸载当前已安装的程序翻译与 Qt 自带翻译。"""
    from PySide6.QtWidgets import QApplication

    global _active_translator, _qtbase_translator
    for translator in (_active_translator, _qtbase_translator):
        if translator is not None:
            QApplication.removeTranslator(translator)
    _active_translator = None
    _qtbase_translator = None


def _install_qtbase_translator(lang: str) -> bool:
    """安装 Qt 自带的 ``qtbase_<lang>.qm``（如 ``zh_CN`` 的对话框按钮文案）。

    PySide6 随包提供 ``qtbase_*.qm``，但默认不加载，缺了它 ``QColorDialog``、
    ``QFileDialog`` 等 Qt 合成控件里的 OK/Cancel、色相/饱和度等仍显示英文。
    语言没有对应文件（如 ``en``，Qt 的源语言就是英文）时静默跳过。

    Args:
        lang: 目标语言代码。

    Returns:
        是否成功安装 Qt 自带翻译。
    """
    from PySide6.QtCore import QLibraryInfo, QTranslator
    from PySide6.QtWidgets import QApplication

    global _qtbase_translator
    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translator = QTranslator()
    if not directory or not translator.load(f"qtbase_{lang}", directory):
        return False
    _qtbase_translator = translator
    QApplication.installTranslator(translator)
    logger.info("Qt 内建控件翻译已安装: qtbase_%s", lang)
    return True
