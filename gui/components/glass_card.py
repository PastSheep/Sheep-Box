"""磨砂毛玻璃卡片组件。

Qt 的 QSS 没有 ``backdrop-filter``，这里的实现是：
「从背景层裁出卡片所在区域 → 高斯模糊 → 在卡片内绘制 → 叠半透明填充 → 圆角遮罩
→ 1px 高光边 → 柔和投影」。三种情况会导致缓存失效并重建：卡片尺寸变化、卡片相对
背景的位置变化、背景版本（主题切换 / 背景图更换）变化。

卡片只依赖设计令牌，不硬编码颜色与尺寸，换主题或换背景时调用方无需改动代码。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from gui.theme.background import BackgroundWidget
from gui.theme.blur import blur_image
from gui.theme.tokens import DesignTokens, tokens_for

__all__ = ["GlassCard"]


class GlassCard(QWidget):
    """半透明磨砂卡片容器。

    Args:
        tokens: 初始设计令牌；不传时按浅色处理。
        parent: 父控件。
    """

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens or tokens_for("light")
        self._backdrop: QImage | None = None
        self._backdrop_key: tuple[int, int, int, int, int] | None = None
        self._shadow = QGraphicsDropShadowEffect(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setGraphicsEffect(self._shadow)
        self._refresh_shadow()

    def set_tokens(self, tokens: DesignTokens) -> None:
        """切换设计令牌；会使已有的模糊背景缓存失效。"""
        if tokens is self._tokens:
            return
        self._tokens = tokens
        self._backdrop = None
        self._backdrop_key = None
        self._refresh_shadow()
        self.update()

    def tokens(self) -> DesignTokens:
        """当前使用的设计令牌。"""
        return self._tokens

    def _refresh_shadow(self) -> None:
        palette = self._tokens.palette
        metrics = self._tokens.metrics
        color = QColor(palette.shadow)
        color.setAlphaF(palette.shadow_alpha)
        self._shadow.setBlurRadius(metrics.shadow_blur)
        self._shadow.setOffset(0, metrics.shadow_offset_y)
        self._shadow.setColor(color)

    def paintEvent(self, event: QPaintEvent) -> None:
        palette = self._tokens.palette
        radius = float(self._tokens.metrics.radius_card)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            backdrop = self._backdrop_image()
            if backdrop is not None:
                painter.save()
                painter.setClipPath(path)
                painter.drawImage(rect.topLeft(), backdrop)
                painter.restore()

            fill = QColor(palette.card_fill)
            fill.setAlphaF(palette.card_fill_alpha)
            painter.fillPath(path, fill)

            painter.save()
            painter.setClipPath(path)
            highlight = QColor(255, 255, 255)
            highlight.setAlphaF(palette.card_highlight_alpha)
            fade = QColor(255, 255, 255)
            fade.setAlphaF(0.0)
            gradient = QLinearGradient(
                rect.topLeft(),
                QPointF(rect.left(), rect.top() + rect.height() * 0.4),
            )
            gradient.setColorAt(0.0, highlight)
            gradient.setColorAt(1.0, fade)
            painter.fillRect(rect, gradient)
            painter.restore()

            border = QColor(palette.card_border)
            border.setAlphaF(palette.card_border_alpha)
            painter.setPen(QPen(border, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        finally:
            painter.end()

    def _backdrop_image(self) -> QImage | None:
        source = self._find_background()
        if source is None:
            return None
        if self._backdrop is not None and source.blur_paused():
            return self._backdrop
        origin = self.mapTo(source, QPoint(0, 0))
        key = (
            self.width(),
            self.height(),
            origin.x(),
            origin.y(),
            source.version(),
        )
        if key == self._backdrop_key and self._backdrop is not None:
            return self._backdrop
        raw = source.backdrop_for(self)
        if raw is None:
            return None
        self._backdrop = blur_image(raw, self._tokens.metrics.glass_blur)
        self._backdrop_key = key
        return self._backdrop

    def _find_background(self) -> BackgroundWidget | None:
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, BackgroundWidget):
                return widget
            widget = widget.parentWidget()
        return None
