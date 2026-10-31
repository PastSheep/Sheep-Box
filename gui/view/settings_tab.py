"""设置标签页：程序级偏好（界面语言切换 + 黑白主题切换）。

设计要点（跨语言布局稳健性，参考主流做法）：
- 用 :class:`QFormLayout` 双栏布局：label 列与 field 列**分别对齐**，
  某一行 label 文本长度随语言变化，不影响 field 控件列位置（不位移）；
- label 列固定宽 + ``wordWrap``：不同语言 label 长度不同也不把输入控件
  顶走，超长换行而非挤压错位；
- 输入控件（下拉）固定宽度，不随 label 或窗口拉伸变形；
- 不硬编码颜色，通过 ``QGroupBox`` / ``QPalette`` 适配黑白主题。

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
from app.theme import SUPPORTED_THEMES, resolve_ui_theme
from config.schema import Theme

__all__ = ["SettingsTab"]

#: 偏好行的 label 列固定宽度（跨语言不变，防位移）。
_LABEL_WIDTH = 140
#: 偏好行的输入控件固定宽度（不随 label / 窗口拉伸变形）。
_FIELD_WIDTH = 160


class SettingsTab(QWidget):
    """设置标签页：程序级偏好（界面语言 + 黑白主题）。

    Attributes:
        language_selected: 用户切换界面语言时发出，参数为目标语言代码
            （如 ``zh_CN`` / ``en``）。
        theme_selected: 用户切换界面主题时发出，参数为目标主题值
            （``light`` / ``dark``）。
    """

    language_selected = Signal(str)
    theme_selected = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        ui_language: str | None = None,
        theme: str | None = None,
    ) -> None:
        super().__init__(parent)

        # 界面偏好组（QFormLayout 双栏：label 列 / field 列分别对齐，防位移）
        self._appearance_group = QGroupBox(self)

        # —— 界面语言行 ——
        self._lang_label = QLabel(self)
        self._lang_label.setFixedWidth(_LABEL_WIDTH)
        self._lang_label.setWordWrap(True)
        self._language_combo = QComboBox(self)
        for display, code in SUPPORTED_UI_LANGUAGES:
            self._language_combo.addItem(display, code)
        current_idx = self._language_combo.findData(resolve_ui_language(ui_language))
        if current_idx >= 0:
            self._language_combo.setCurrentIndex(current_idx)
        self._language_combo.setFixedWidth(_FIELD_WIDTH)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)

        # —— 主题行 ——
        self._theme_label = QLabel(self)
        self._theme_label.setFixedWidth(_LABEL_WIDTH)
        self._theme_label.setWordWrap(True)
        self._theme_combo = QComboBox(self)
        for display, value in SUPPORTED_THEMES:
            self._theme_combo.addItem(display, value)
        theme_idx = self._theme_combo.findData(resolve_ui_theme(theme))
        if theme_idx >= 0:
            self._theme_combo.setCurrentIndex(theme_idx)
        self._theme_combo.setFixedWidth(_FIELD_WIDTH)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow(self._lang_label, self._language_combo)
        form.addRow(self._theme_label, self._theme_combo)
        self._appearance_group.setLayout(form)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._appearance_group)
        layout.addStretch()

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """重设界面文本（语言切换后由主窗口调用刷新）。"""
        self._appearance_group.setTitle(self.tr("Appearance"))
        self._lang_label.setText(self.tr("UI Language"))
        self._theme_label.setText(self.tr("Theme"))
        # 主题选项显示名：字面量 tr() 供 lupdate 提取
        light_idx = self._theme_combo.findData(Theme.LIGHT.value)
        if light_idx >= 0:
            self._theme_combo.setItemText(light_idx, self.tr("Light"))
        dark_idx = self._theme_combo.findData(Theme.DARK.value)
        if dark_idx >= 0:
            self._theme_combo.setItemText(dark_idx, self.tr("Dark"))

    def _on_language_changed(self, index: int) -> None:
        code = self._language_combo.itemData(index)
        if code:
            self.language_selected.emit(str(code))

    def _on_theme_changed(self, index: int) -> None:
        value = self._theme_combo.itemData(index)
        if value:
            self.theme_selected.emit(str(value))
