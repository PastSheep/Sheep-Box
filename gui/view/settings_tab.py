"""设置页：程序级偏好（界面语言 + 黑白主题）。

页面只有一个磨砂玻璃卡片：卡片内是「分区标签 + 若干偏好行」，行由
:class:`FieldRow` 提供，标签列与控件列各自固定宽度，切换语言时控件不位移。
页面上不再放标题与说明文字——标题栏已经标明当前页面，设置页也不承载
OCR 等业务模块的运行参数（那些走 config.yaml，由真正的业务模块消费）。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.i18n import SUPPORTED_UI_LANGUAGES, resolve_ui_language
from app.theme import SUPPORTED_THEMES, resolve_ui_theme
from config.schema import Theme
from gui.components.field_row import FieldRow
from gui.components.glass_card import GlassCard
from gui.components.select_combo import SelectComboBox
from gui.theme.tokens import DesignTokens, tokens_for

__all__ = ["SettingsTab"]


class SettingsTab(QWidget):
    """设置页：程序级偏好（界面语言 + 黑白主题）。

    Attributes:
        language_selected: 用户切换界面语言时发出，参数为目标语言代码。
        theme_selected: 用户切换界面主题时发出，参数为 ``light`` / ``dark``。
    """

    language_selected = Signal(str)
    theme_selected = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        ui_language: str | None = None,
        theme: str | None = None,
        tokens: DesignTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens or tokens_for(resolve_ui_theme(theme))
        metrics = self._tokens.metrics

        self._card = GlassCard(tokens=self._tokens, parent=self)
        self._section = QLabel(self._card)
        self._section.setObjectName("SectionLabel")

        self._language_combo = SelectComboBox(self._tokens, self._card)
        for display, code in SUPPORTED_UI_LANGUAGES:
            self._language_combo.addItem(display, code)
        current_index = self._language_combo.findData(resolve_ui_language(ui_language))
        if current_index >= 0:
            self._language_combo.setCurrentIndex(current_index)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)

        self._theme_combo = SelectComboBox(self._tokens, self._card)
        for display, value in SUPPORTED_THEMES:
            self._theme_combo.addItem(display, value)
        theme_index = self._theme_combo.findData(resolve_ui_theme(theme))
        if theme_index >= 0:
            self._theme_combo.setCurrentIndex(theme_index)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        self._language_row = FieldRow(
            "",
            self._language_combo,
            tokens=self._tokens,
            show_divider=False,
            parent=self._card,
        )
        self._theme_row = FieldRow(
            "",
            self._theme_combo,
            tokens=self._tokens,
            show_divider=True,
            parent=self._card,
        )

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(
            metrics.space_lg, metrics.space_lg, metrics.space_lg, metrics.space_md
        )
        card_layout.setSpacing(metrics.space_xs + 2)
        card_layout.addWidget(self._section)
        card_layout.addWidget(self._language_row)
        card_layout.addWidget(self._theme_row)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(
            metrics.space_xl, metrics.space_xl, metrics.space_xl, metrics.space_xl
        )
        page_layout.setSpacing(0)
        page_layout.addWidget(self._card, 0)
        page_layout.addStretch(1)

        self.retranslate_ui()

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """主题切换时更新令牌（卡片会重建模糊背景）。"""
        self._tokens = tokens
        self._card.set_tokens(tokens)
        self._language_row.apply_tokens(tokens)
        self._theme_row.apply_tokens(tokens)
        self._language_combo.set_tokens(tokens)
        self._theme_combo.set_tokens(tokens)

    def retranslate_ui(self) -> None:
        """重设界面文本（语言切换后由主窗口调用）。"""
        self._section.setText(self.tr("Appearance"))
        self._language_row.set_label_text(self.tr("UI Language"))
        self._theme_row.set_label_text(self.tr("Theme"))
        # 主题选项显示名：写字面量 tr() 供 lupdate 静态提取
        light_index = self._theme_combo.findData(Theme.LIGHT.value)
        if light_index >= 0:
            self._theme_combo.setItemText(light_index, self.tr("Light"))
        dark_index = self._theme_combo.findData(Theme.DARK.value)
        if dark_index >= 0:
            self._theme_combo.setItemText(dark_index, self.tr("Dark"))

    def _on_language_changed(self, index: int) -> None:
        code = self._language_combo.itemData(index)
        if code:
            self.language_selected.emit(str(code))

    def _on_theme_changed(self, index: int) -> None:
        value = self._theme_combo.itemData(index)
        if value:
            self.theme_selected.emit(str(value))
