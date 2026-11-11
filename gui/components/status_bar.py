"""底部状态栏：CPU / GPU / 内存利用率与压力着色点。

状态栏只负责「显示」，采样节奏由主窗口的定时器驱动（间隔取
``app.status_bar.refresh_interval_ms``）；本组件不持有采集器、不起线程。

布局固定在右侧：靠左留白，指标从右往左排列为 CPU → GPU → 内存，主窗口拉伸
时只有左侧留白变化，指标位置不随窗口宽度漂移。数值用固定宽度右对齐，避免
百分比位数变化时整行左右跳。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from gui.components.usage_gradient import UsageGradient
from gui.theme.tokens import DesignTokens, tokens_for
from service.sysinfo.models import SystemSnapshot

__all__ = ["StatusBar"]

#: 状态栏高度（含 1px 分隔线）
STATUS_BAR_HEIGHT = 26
#: 压力点直径
_DOT_SIZE = 8
#: 数值列宽度（容纳 "100%"）
_VALUE_WIDTH = 40
#: 指标之间的水平间距
_ITEM_SPACING = 20


class _PressureDot(QWidget):
    """压力色点：纯色小圆，颜色由渐变按利用率求得。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#17A05E")
        self.setFixedSize(_DOT_SIZE, _DOT_SIZE)

    def set_color(self, color: QColor) -> None:
        """更新点颜色并重绘。"""
        if color == self._color:
            return
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制圆形色点。"""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color)
            painter.drawEllipse(QRectF(self.rect()))
        finally:
            painter.end()


class _UsageItem(QWidget):
    """单项指标：名称 + 百分比 + 压力点。"""

    def __init__(
        self,
        label: str,
        tokens: DesignTokens,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._label = QLabel(label, self)
        self._label.setObjectName("StatusLabel")
        self._value = QLabel("—", self)
        self._value.setObjectName("StatusValue")
        self._value.setFixedWidth(_VALUE_WIDTH)
        self._value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._dot = _PressureDot(self)
        self._dot.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._value, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.apply_tokens(tokens)

    def set_label(self, text: str) -> None:
        """更新指标名称（语言切换 / GPU 序号变化时调用）。"""
        self._label.setText(text)

    def set_value(self, percent: float | None, gradient: UsageGradient | None) -> None:
        """更新数值与压力点颜色；``None`` 表示该指标不可用。

        Args:
            percent: 利用率百分比；None 时显示占位符并隐藏压力点。
            gradient: 取色用的渐变；None 时只更新数值。
        """
        if percent is None:
            self._value.setText("—")
            self._dot.setVisible(False)
            return
        self._value.setText(f"{percent:.0f}%")
        if gradient is not None:
            self._dot.set_color(gradient.color_at(percent))
        self._dot.setVisible(True)

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """主题切换时更新字体与颜色。"""
        self._tokens = tokens
        palette = tokens.palette
        metrics = tokens.metrics
        self._label.setStyleSheet(
            f"color: {palette.text_muted}; font-size: {metrics.font_caption}px;"
        )
        self._value.setStyleSheet(
            f"color: {palette.text_primary}; font-size: {metrics.font_body}px;"
            " font-weight: 600;"
        )


class StatusBar(QWidget):
    """底部状态栏：右侧显示 CPU / GPU / 内存利用率。

    Args:
        tokens: 设计令牌；不传按浅色处理。
        stops: 渐变锚点 ``[(位置, #RRGGBB), ...]``；不传时用默认三色梯度。
        parent: 父控件。
    """

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        stops: list[tuple[float, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens or tokens_for("light")
        self._gradient = UsageGradient(
            stops
            or [
                (0.0, "#17A05E"),
                (50.0, "#E0A008"),
                (80.0, "#D94A4A"),
                (100.0, "#D94A4A"),
            ]
        )
        self.setFixedHeight(STATUS_BAR_HEIGHT)

        self._cpu_item = _UsageItem("CPU", self._tokens, self)
        self._mem_item = _UsageItem("MEM", self._tokens, self)
        self._gpu_items: list[_UsageItem] = []
        self._gpu_host = QWidget(self)
        self._gpu_layout = QHBoxLayout(self._gpu_host)
        self._gpu_layout.setContentsMargins(0, 0, 0, 0)
        self._gpu_layout.setSpacing(_ITEM_SPACING)

        self._row = QHBoxLayout(self)
        margins = self._tokens.metrics
        self._row.setContentsMargins(margins.space_xl, 0, margins.space_xl, 0)
        self._row.setSpacing(_ITEM_SPACING)
        self._row.addStretch(1)
        self._row.addWidget(self._cpu_item, 0, Qt.AlignmentFlag.AlignVCenter)
        self._row.addWidget(self._gpu_host, 0, Qt.AlignmentFlag.AlignVCenter)
        self._row.addWidget(self._mem_item, 0, Qt.AlignmentFlag.AlignVCenter)

        self._gpu_host.setVisible(False)
        self.retranslate_ui()

    # ------------------------------------------------------------ 配置与主题

    def set_gradient_stops(self, stops: list[tuple[float, str]]) -> None:
        """更新渐变锚点（设置项变化后由主窗口调用）。"""
        self._gradient = UsageGradient(stops)
        self.update()

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """主题切换时更新令牌。"""
        self._tokens = tokens
        self._cpu_item.apply_tokens(tokens)
        self._mem_item.apply_tokens(tokens)
        for item in self._gpu_items:
            item.apply_tokens(tokens)
        self.update()

    def retranslate_ui(self) -> None:
        """重设指标名称（语言切换后调用）。"""
        self._cpu_item.set_label(self.tr("CPU"))
        self._mem_item.set_label(self.tr("MEM"))
        self._refresh_gpu_labels()

    # ------------------------------------------------------------ 数据刷新

    def apply_snapshot(self, snapshot: SystemSnapshot) -> None:
        """用一次采样结果刷新三项指标。

        Args:
            snapshot: 采集器返回的设备快照。
        """
        self._cpu_item.set_value(snapshot.cpu.percent, self._gradient)
        self._mem_item.set_value(snapshot.memory.percent, self._gradient)
        self._sync_gpu_items(snapshot)

    def _sync_gpu_items(self, snapshot: SystemSnapshot) -> None:
        """按 GPU 数量增删指标项并刷新读数。"""
        gpus = snapshot.gpus
        if not gpus:
            for item in self._gpu_items:
                item.setParent(None)
                item.deleteLater()
            self._gpu_items = []
            self._gpu_host.setVisible(False)
            return

        while len(self._gpu_items) < len(gpus):
            item = _UsageItem("GPU", self._tokens, self._gpu_host)
            self._gpu_layout.addWidget(item, 0, Qt.AlignmentFlag.AlignVCenter)
            self._gpu_items.append(item)
        while len(self._gpu_items) > len(gpus):
            extra = self._gpu_items.pop()
            extra.setParent(None)
            extra.deleteLater()

        self._gpu_host.setVisible(True)
        self._refresh_gpu_labels()
        for item, gpu in zip(self._gpu_items, gpus, strict=False):
            item.set_value(gpu.utilization_percent, self._gradient)

    def _refresh_gpu_labels(self) -> None:
        """GPU 名称：单卡显示 ``GPU``，多卡追加序号。"""
        total = len(self._gpu_items)
        for index, item in enumerate(self._gpu_items):
            if total == 1:
                item.set_label(self.tr("GPU"))
            else:
                item.set_label(self.tr("GPU %1").replace("%1", str(index + 1)))

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制顶部分隔线（底色由背景层透出）。"""
        painter = QPainter(self)
        try:
            palette = self._tokens.palette
            line = QColor(palette.divider)
            line.setAlphaF(palette.divider_alpha)
            painter.setPen(QPen(line, 1.0))
            painter.drawLine(QPointF(0, 0.5), QPointF(self.width(), 0.5))
        finally:
            painter.end()
