"""主窗口与 GUI 启动入口。"""

from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

from gui.controller.settings_controller import SettingsController
from gui.view.settings_tab import SettingsTab

__all__ = ["MainWindow", "run_gui"]


class MainWindow(QMainWindow):
    """应用主窗口：以标签页组织各功能（首版仅"设置"页）。"""

    def __init__(
        self, controller: SettingsController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sheep Box 设置")
        self._tabs = QTabWidget(self)
        self._tabs.addTab(SettingsTab(controller), "设置")
        self.setCentralWidget(self._tabs)
        self.resize(600, 480)


def run_gui(config_path: str | Path) -> int:
    """启动 GUI 应用（阻塞运行，返回退出码）。

    Args:
        config_path: 配置文件（``config/config.yaml``）路径。
    """
    from config.manager import ConfigManager

    app = QApplication.instance() or QApplication([])
    config_manager = ConfigManager(config_path)
    window = MainWindow(SettingsController(config_manager))
    window.show()
    return app.exec()
