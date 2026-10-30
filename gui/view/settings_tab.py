"""设置标签页：程序级偏好（当前承载界面语言切换）。

设置界面承载整个程序的偏好配置（如黑白主题、界面语言切换等），
不承载 OCR 等业务模块的运行参数（由业务模块经 config.yaml / 运行时传入）。
当前首个偏好项为「界面语言」（i18n）。
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.i18n import SUPPORTED_UI_LANGUAGES, resolve_ui_language

__all__ = ["SettingsTab"]


class SettingsTab(QWidget):
    """设置标签页：程序级偏好（当前：界面语言切换）。

    Attributes:
        language_selected: 用户切换界面语言时发出，参数为目标语言代码
            （如 ``zh_CN`` / ``en``）。
    """

    language_selected = Signal(str)

    def __init__(
        self, parent: QWidget | None = None, ui_language: str | None = None
    ) -> None:
        super().__init__(parent)
        self._lang_label = QLabel(self)
        self._language_combo = QComboBox(self)
        for display, code in SUPPORTED_UI_LANGUAGES:
            self._language_combo.addItem(display, code)
        current_idx = self._language_combo.findData(resolve_ui_language(ui_language))
        if current_idx >= 0:
            self._language_combo.setCurrentIndex(current_idx)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)

        self._info_label = QLabel(self)
        self._info_label.setWordWrap(True)

        lang_row = QHBoxLayout()
        lang_row.addWidget(self._lang_label)
        lang_row.addWidget(self._language_combo)
        lang_row.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(lang_row)
        layout.addWidget(self._info_label)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """重设界面文本（语言切换后由主窗口调用刷新）。"""
        self._lang_label.setText(self.tr("UI Language"))
        self._info_label.setText(
            self.tr(
                "No settings available yet.\n"
                "The settings screen will host program-level preferences "
                "(e.g. theme, UI language). OCR module parameters are not "
                "configured here."
            )
        )

    def _on_language_changed(self, index: int) -> None:
        code = self._language_combo.itemData(index)
        if code:
            self.language_selected.emit(str(code))
