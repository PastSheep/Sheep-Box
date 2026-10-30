"""主窗口与 GUI 启动入口。"""

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

from gui.view.settings_tab import SettingsTab

__all__ = ["MainWindow", "run_gui"]


class MainWindow(QMainWindow):
    """应用主窗口：以标签页组织各功能（首版仅"设置"页）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Sheep Box Settings"))
        self._tabs = QTabWidget(self)
        self._tabs.addTab(SettingsTab(), self.tr("Settings"))
        self.setCentralWidget(self._tabs)
        self.resize(600, 480)


def run_gui(language: str | None = None) -> int:
    """启动 GUI 应用（阻塞运行，返回退出码）。

    Args:
        language: 界面语言（如 ``zh_CN``）；缺省按程序偏好解析。
    """
    from app.i18n import install_ui_translator

    app = QApplication.instance() or QApplication([])
    install_ui_translator(language)
    window = MainWindow()
    window.show()
    return app.exec()
