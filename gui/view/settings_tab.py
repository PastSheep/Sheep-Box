"""设置标签页：程序级偏好（当前为空占位）。

设置界面承载整个程序的偏好配置（如黑白主题、界面语言切换等），
不承载 OCR 等业务模块的运行参数（由业务模块经 config.yaml / 运行时传入）。
当前暂无程序级偏好项，待后续实现后再填充表单。
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

__all__ = ["SettingsTab"]


class SettingsTab(QWidget):
    """设置标签页：程序级偏好（暂空占位，待主题 / 界面语言等偏好项落地）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        label = QLabel(
            self.tr(
                "No settings available yet.\n"
                "The settings screen will host program-level preferences "
                "(e.g. theme, UI language). OCR module parameters are not "
                "configured here."
            )
        )
        label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
