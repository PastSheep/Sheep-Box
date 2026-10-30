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

# 持有当前 QTranslator 引用，防止被 GC 回收导致翻译失效（Qt 要求翻译器
# 与应用同生命周期）。
_active_translator: QTranslator | None = None


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

    Args:
        language: 界面语言（如 ``zh_CN``）；缺省使用 :func:`resolve_ui_language`。

    Returns:
        是否成功安装翻译；无匹配 ``.qm`` 时回退英文源并返回 ``False``。
    """
    from PySide6.QtCore import QTranslator
    from PySide6.QtWidgets import QApplication

    global _active_translator
    lang = resolve_ui_language(language)
    translator = QTranslator()
    if translator.load(lang, str(I18N_DIR)):
        _active_translator = translator
        QApplication.installTranslator(translator)
        logger.info("界面语言已安装: %s", lang)
        return True
    logger.info("界面语言翻译未找到: %s（回退英文源）", lang)
    return False
