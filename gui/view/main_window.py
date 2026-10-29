"""主窗口与 GUI 启动入口。"""

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


def run_gui(controller: SettingsController) -> int:
    """启动 GUI 应用（阻塞运行，返回退出码）。

    依赖对象由调用方（main.py 经 bootstrap）组装后传入，本函数只负责
    创建应用与窗口，不再内部 ``new`` 依赖。
    """
    app = QApplication.instance() or QApplication([])
    window = MainWindow(controller)
    window.show()
    return app.exec()
