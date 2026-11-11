"""设置页：程序级偏好（界面语言、黑白主题、状态栏刷新节奏与压力着色）。

页面是两张磨砂玻璃卡片：
1. **外观**：界面语言、主题；
2. **状态栏**：刷新间隔、压力着色渐变锚点。

前一张用 :class:`FieldRow`（标签列与控件列固定宽度，切语言不位移），后一张的
渐变条需要横向铺满，改用 :class:`WideFieldRow`。

页面不放标题与说明文字——标题栏已标明当前页面；设置页只承载程序级偏好，
OCR 等业务模块的运行参数留在 ``config.yaml`` 由真正的业务模块消费。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.i18n import SUPPORTED_UI_LANGUAGES, resolve_ui_language
from app.theme import SUPPORTED_THEMES, resolve_ui_theme
from config.schema import StatusBarConfig, Theme
from gui.components.field_row import FieldRow
from gui.components.glass_card import GlassCard
from gui.components.gradient_stops import GradientStopsControl
from gui.components.select_combo import SelectComboBox
from gui.components.wide_field_row import WideFieldRow
from gui.theme.tokens import DesignTokens, tokens_for

__all__ = ["SettingsTab"]

#: 可选刷新间隔（毫秒, 显示文本）。显示文本是数值单位，不参与翻译。
_REFRESH_INTERVALS: tuple[tuple[int, str], ...] = (
    (500, "0.5 s"),
    (1000, "1 s"),
    (2000, "2 s"),
    (5000, "5 s"),
)

#: 配置缺失时的兜底锚点（与 ``config.schema`` 默认值一致）
_FALLBACK_STOPS: tuple[tuple[float, str], ...] = (
    (0.0, "#17A05E"),
    (50.0, "#E0A008"),
    (80.0, "#D94A4A"),
    (100.0, "#D94A4A"),
)


class SettingsTab(QWidget):
    """设置页：程序级偏好。

    Attributes:
        language_selected: 用户切换界面语言时发出，参数为目标语言代码。
        theme_selected: 用户切换界面主题时发出，参数为 ``light`` / ``dark``。
        refresh_interval_selected: 用户切换状态栏刷新间隔，参数为毫秒。
        gradient_stops_changed: 用户编辑压力着色锚点，参数为
            ``[(位置, #RRGGBB), ...]``。
    """

    language_selected = Signal(str)
    theme_selected = Signal(str)
    refresh_interval_selected = Signal(int)
    gradient_stops_changed = Signal(list)

    def __init__(
        self,
        parent: QWidget | None = None,
        ui_language: str | None = None,
        theme: str | None = None,
        status_bar: StatusBarConfig | None = None,
        tokens: DesignTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens or tokens_for(resolve_ui_theme(theme))
        metrics = self._tokens.metrics
        status_config = status_bar or StatusBarConfig()

        # ---------------------------------------------------- 外观卡片
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

        # ---------------------------------------------------- 状态栏卡片
        self._status_card = GlassCard(tokens=self._tokens, parent=self)
        self._status_section = QLabel(self._status_card)
        self._status_section.setObjectName("SectionLabel")

        self._interval_combo = SelectComboBox(self._tokens, self._status_card)
        for milliseconds, display in _REFRESH_INTERVALS:
            self._interval_combo.addItem(display, milliseconds)
        interval_index = self._interval_combo.findData(
            status_config.refresh_interval_ms
        )
        if interval_index < 0:
            interval_index = self._interval_combo.findData(1000)
        if interval_index >= 0:
            self._interval_combo.setCurrentIndex(interval_index)
        self._interval_combo.currentIndexChanged.connect(self._on_interval_changed)

        self._interval_row = FieldRow(
            "",
            self._interval_combo,
            tokens=self._tokens,
            show_divider=False,
            parent=self._status_card,
        )

        stops = [
            (stop.at, stop.color) for stop in status_config.gradient_stops
        ] or list(_FALLBACK_STOPS)
        self._stops_control = GradientStopsControl(
            tokens=self._tokens, stops=stops, parent=self._status_card
        )
        self._stops_control.stops_changed.connect(self.gradient_stops_changed.emit)
        self._stops_row = WideFieldRow(
            "",
            self._stops_control,
            tokens=self._tokens,
            show_divider=True,
            parent=self._status_card,
        )

        status_layout = QVBoxLayout(self._status_card)
        status_layout.setContentsMargins(
            metrics.space_lg, metrics.space_lg, metrics.space_lg, metrics.space_lg
        )
        status_layout.setSpacing(metrics.space_xs + 2)
        status_layout.addWidget(self._status_section)
        status_layout.addWidget(self._interval_row)
        status_layout.addWidget(self._stops_row)

        # ---------------------------------------------------- 页面布局
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(
            metrics.space_xl, metrics.space_xl, metrics.space_xl, metrics.space_xl
        )
        page_layout.setSpacing(metrics.space_lg)
        page_layout.addWidget(self._card, 0)
        page_layout.addWidget(self._status_card, 0)
        page_layout.addStretch(1)

        self.retranslate_ui()

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """主题切换时更新令牌（卡片会重建模糊背景）。"""
        self._tokens = tokens
        self._card.set_tokens(tokens)
        self._status_card.set_tokens(tokens)
        self._language_row.apply_tokens(tokens)
        self._theme_row.apply_tokens(tokens)
        self._interval_row.apply_tokens(tokens)
        self._stops_row.apply_tokens(tokens)
        self._language_combo.set_tokens(tokens)
        self._theme_combo.set_tokens(tokens)
        self._interval_combo.set_tokens(tokens)
        self._stops_control.apply_tokens(tokens)

    def retranslate_ui(self) -> None:
        """重设界面文本（语言切换后由主窗口调用）。"""
        self._section.setText(self.tr("Appearance"))
        self._language_row.set_label_text(self.tr("UI Language"))
        self._theme_row.set_label_text(self.tr("Theme"))
        self._status_section.setText(self.tr("Status Bar"))
        self._interval_row.set_label_text(self.tr("Refresh Interval"))
        self._stops_row.set_label_text(self.tr("Pressure Colors"))
        # 主题选项显示名：写字面量 tr() 供 lupdate 静态提取
        light_index = self._theme_combo.findData(Theme.LIGHT.value)
        if light_index >= 0:
            self._theme_combo.setItemText(light_index, self.tr("Light"))
        dark_index = self._theme_combo.findData(Theme.DARK.value)
        if dark_index >= 0:
            self._theme_combo.setItemText(dark_index, self.tr("Dark"))
        self._stops_control.retranslate_ui()

    # ---------------------------------------------------------------- 回调

    def _on_language_changed(self, index: int) -> None:
        code = self._language_combo.itemData(index)
        if code:
            self.language_selected.emit(str(code))

    def _on_theme_changed(self, index: int) -> None:
        value = self._theme_combo.itemData(index)
        if value:
            self.theme_selected.emit(str(value))

    def _on_interval_changed(self, index: int) -> None:
        value = self._interval_combo.itemData(index)
        if value:
            self.refresh_interval_selected.emit(int(value))
