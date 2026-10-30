"""主窗口与 GUI 启动入口。"""

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

from common.exceptions import ConfigError
from gui.view.settings_tab import SettingsTab

if TYPE_CHECKING:
    from config.manager import ConfigManager

logger = logging.getLogger(__name__)

__all__ = ["MainWindow", "run_gui"]


class MainWindow(QMainWindow):
    """应用主窗口：以标签页组织各功能（当前仅"设置"页）。

    Args:
        parent: 父控件。
        config_manager: 通用配置中心；提供时语言切换可持久化到
            ``app.ui_language``，缺失（config 无效）时仅即时切换不持久化。
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        config_manager: "ConfigManager | None" = None,
    ) -> None:
        super().__init__(parent)
        self._config_manager: ConfigManager | None = config_manager
        self._settings_tab = SettingsTab(ui_language=self._current_ui_language())
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._settings_tab, "")
        self.setCentralWidget(self._tabs)
        self.resize(600, 480)
        self._settings_tab.language_selected.connect(self._on_language_selected)
        self.retranslate_ui()

    def _current_ui_language(self) -> str | None:
        """读取当前程序偏好的界面语言；config 不可用时返回 None（回退默认）。"""
        if self._config_manager is None:
            return None
        try:
            return self._config_manager.app().ui_language
        except ConfigError:
            logger.warning("读取界面语言失败，回退默认 zh_CN", exc_info=True)
            return None

    def _on_language_selected(self, language: str) -> None:
        """用户切换界面语言：切翻译 → 持久化 → 刷新界面文本。"""
        from app.i18n import switch_ui_language

        switch_ui_language(language)
        if self._config_manager is not None:
            try:
                self._config_manager.save_app({"ui_language": language})
            except ConfigError:
                logger.warning("界面语言写回失败: %s", language, exc_info=True)
        self.retranslate_ui()
        self._settings_tab.retranslate_ui()

    def retranslate_ui(self) -> None:
        """重设主窗口界面文本（语言切换后刷新）。"""
        self.setWindowTitle(self.tr("Sheep Box Settings"))
        self._tabs.setTabText(0, self.tr("Settings"))


def run_gui(
    language: str | None = None, config_manager: "ConfigManager | None" = None
) -> int:
    """启动 GUI 应用（阻塞运行，返回退出码）。

    Args:
        language: 界面语言（如 ``zh_CN``）；缺省按程序偏好解析。
        config_manager: 通用配置中心；提供时语言切换可持久化。
    """
    from app.i18n import install_ui_translator

    app = QApplication.instance() or QApplication([])
    install_ui_translator(language)
    window = MainWindow(config_manager=config_manager)
    window.show()
    return app.exec()
