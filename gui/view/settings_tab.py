"""设置标签页：程序级偏好（当前：界面语言切换）。

设计要点（跨语言布局稳健性，参考主流做法）：
- 用 :class:`QFormLayout` 双栏布局：label 列与 field 列**分别对齐**，
  某一行 label 文本长度随语言变化，不影响 field 控件列位置（不位移）；
- 输入控件（下拉）用固定宽度，不随 label 或窗口拉伸变形；
- 说明文字自动换行（``wordWrap``），长文本换行而非挤压错位；
- 不硬编码颜色，通过 ``QGroupBox`` / ``QPalette`` 适配未来的黑白主题。

设置界面承载整个程序的偏好配置（如黑白主题、界面语言切换等），
不承载 OCR 等业务模块的运行参数（由业务模块经 config.yaml / 运行时传入）。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

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

        # 界面语言组（QFormLayout 双栏：label 列 / field 列分别对齐，防位移）
        self._appearance_group = QGroupBox(self)
        self._lang_label = QLabel(self)
        # 固定 label 列宽：不同语言 label 长度不同也不把 field 控件顶走（防位移），
        # 超长 label 用换行而非挤压错位。
        self._lang_label.setFixedWidth(140)
        self._lang_label.setWordWrap(True)
        self._language_combo = QComboBox(self)
        for display, code in SUPPORTED_UI_LANGUAGES:
            self._language_combo.addItem(display, code)
        current_idx = self._language_combo.findData(resolve_ui_language(ui_language))
        if current_idx >= 0:
            self._language_combo.setCurrentIndex(current_idx)
        # 固定字段宽：不随 label 文本长度 / 语言变化而位移或变形
        self._language_combo.setFixedWidth(160)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow(self._lang_label, self._language_combo)
        self._appearance_group.setLayout(form)

        # 说明文字：次要、自动换行（长文本换行而非挤压错位）
        self._hint_label = QLabel(self)
        self._hint_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._appearance_group)
        layout.addWidget(self._hint_label)
        layout.addStretch()

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """重设界面文本（语言切换后由主窗口调用刷新）。"""
        self._appearance_group.setTitle(self.tr("Appearance"))
        self._lang_label.setText(self.tr("UI Language"))
        self._hint_label.setText(
            self.tr("Language changes take effect immediately and are saved.")
        )

    def _on_language_changed(self, index: int) -> None:
        code = self._language_combo.itemData(index)
        if code:
            self.language_selected.emit(str(code))
