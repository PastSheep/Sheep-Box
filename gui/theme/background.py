"""主窗口背景层：底色渐变 + 低饱和光斑，可替换为图片背景。

玻璃卡片通过 :meth:`BackgroundWidget.backdrop_for` 取得自身区域的背景像素，
再做模糊，形成"背景透过卡片"的毛玻璃效果。背景内容变化（主题切换、尺寸变化、
换图）时自增版本号，卡片据此让缓存失效。

为什么默认不是纯色：模糊纯色仍是纯色，磨砂质感只能从有色阶的背景里透出来，
所以默认用「底色渐变 + 两处柔光斑」；将来要换图片背景，只需调用
:meth:`BackgroundWidget.set_image`，卡片侧无需改动。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from gui.theme.blur import blur_image

if TYPE_CHECKING:
    from gui.theme.tokens import DesignTokens

logger = logging.getLogger(__name__)

__all__ = ["BackgroundWidget"]


class BackgroundWidget(QWidget):
    """内容区背景层（作为主窗口 central widget 的底层容器）。

    Args:
        tokens: 当前设计令牌。
        parent: 父控件。
        image_path: 自定义背景图片路径；不传则使用渐变 + 光斑。
    """

    def __init__(
        self,
        tokens: DesignTokens,
        parent: QWidget | None = None,
        image_path: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens
        self._image_path: str | None = image_path
        self._image: QImage | None = None
        self._cover: QImage | None = None
        self._cover_size: QSize | None = None
        self._cache: QImage | None = None
        self._version = 0
        self._blur_paused = False
        self.setAutoFillBackground(False)
        # 承载焦点：避免窗口首次显示时第一个下拉框被自动高亮（观感上像误触）
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if image_path:
            self._load_image(image_path)

    def set_tokens(self, tokens: DesignTokens) -> None:
        """切换设计令牌（主题变化时调用）。"""
        if tokens is self._tokens:
            return
        self._tokens = tokens
        self._invalidate()

    def set_image(self, path: str | None) -> None:
        """设置背景图片；传 ``None`` 回退渐变光斑背景。"""
        self._image_path = path
        self._image = None
        if path:
            self._load_image(path)
        else:
            self._invalidate()

    def version(self) -> int:
        """背景版本号（内容变化时自增，供卡片缓存失效判断）。"""
        return self._version

    def set_blur_paused(self, paused: bool) -> None:
        """暂停/恢复卡片重新取背景。

        拖动、缩放窗口时每帧重算模糊会掉帧；暂停期间卡片沿用上一帧的模糊结果，
        结束后再重算一次，观感上只是模糊层"贴住不动"，代价比重绘掉帧小得多。
        """
        self._blur_paused = paused

    def blur_paused(self) -> bool:
        """是否处于暂停重算状态。"""
        return self._blur_paused

    def backdrop_for(self, widget: QWidget) -> QImage | None:
        """取 ``widget`` 在背景层中的对应区域（未模糊，含设备像素比）。

        Args:
            widget: 需要取背景的子控件。

        Returns:
            背景切片；控件不在背景范围内时返回 ``None``。
        """
        self._ensure_cache()
        if self._cache is None:
            return None
        dpr = self.devicePixelRatioF()
        origin = widget.mapTo(self, QPoint(0, 0))
        rect = QRect(
            round(origin.x() * dpr),
            round(origin.y() * dpr),
            round(widget.width() * dpr),
            round(widget.height() * dpr),
        )
        rect = rect.intersected(self._cache.rect())
        if rect.width() <= 0 or rect.height() <= 0:
            return None
        return self._cache.copy(rect)

    def paintEvent(self, event: QPaintEvent) -> None:
        # 背景（渐变 + 光斑 / 虚化图片）只在尺寸变化时重算一次，这里直接贴缓存，
        # 避免每次重绘都做缩放与光斑合成。
        self._ensure_cache()
        painter = QPainter(self)
        try:
            if self._cache is not None:
                painter.drawImage(QPoint(0, 0), self._cache)
        finally:
            painter.end()

    def _cover_image(self, size: QSize) -> QImage | None:
        """按 cover 规则裁剪图片并的整体虚化（缓存，仅尺寸变化时重算）。

        背景图直接清晰铺满会让前景文本难以辨认，主流做法是「图片虚化 + 色调
        遮罩」，这里先裁剪到目标尺寸再高斯模糊。
        """
        if self._image is None or size.width() <= 0 or size.height() <= 0:
            return None
        if self._cover is not None and self._cover_size == size:
            return self._cover
        scaled = self._image.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        offset_x = max(0, (scaled.width() - size.width()) // 2)
        offset_y = max(0, (scaled.height() - size.height()) // 2)
        cropped = scaled.copy(offset_x, offset_y, size.width(), size.height())
        self._cover = blur_image(cropped, self._tokens.metrics.image_blur)
        self._cover_size = size
        return self._cover

    def _load_image(self, path: str) -> None:
        image = QImage(path)
        if image.isNull():
            logger.warning("背景图片加载失败: %s", path)
            self._invalidate()
            return
        self._image = image
        self._invalidate()

    def _invalidate(self) -> None:
        self._cache = None
        self._cover = None
        self._cover_size = None
        self._version += 1
        self.update()

    def _pixel_size(self) -> QSize:
        dpr = self.devicePixelRatioF()
        return QSize(round(self.width() * dpr), round(self.height() * dpr))

    def _ensure_cache(self) -> None:
        size = self._pixel_size()
        if size.width() <= 0 or size.height() <= 0:
            return
        if self._cache is not None and self._cache.size() == size:
            return
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.devicePixelRatioF())
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            self._paint_background(painter, QRect(0, 0, self.width(), self.height()))
        finally:
            painter.end()
        self._cache = image
        self._version += 1

    def _paint_background(self, painter: QPainter, rect: QRect) -> None:
        palette = self._tokens.palette
        if self._image is not None:
            cover = self._cover_image(rect.size())
            if cover is not None:
                painter.drawImage(rect.topLeft(), cover)
            # 色调遮罩：保证前景文本在任意图片上都可读
            scrim = QColor(palette.bg_base)
            scrim.setAlphaF(palette.image_scrim_alpha)
            painter.fillRect(rect, scrim)
            return
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(palette.bg_base))
        gradient.setColorAt(1.0, QColor(palette.bg_gradient_end))
        painter.fillRect(rect, gradient)

        width = float(rect.width())
        height = float(rect.height())
        self._draw_glow(
            painter,
            width * 0.30,
            height * 0.06,
            width * 0.52,
            palette.glow_primary,
            palette.glow_primary_alpha,
        )
        self._draw_glow(
            painter,
            width * 0.88,
            height * 0.82,
            width * 0.46,
            palette.glow_secondary,
            palette.glow_secondary_alpha,
        )

    @staticmethod
    def _draw_glow(
        painter: QPainter,
        center_x: float,
        center_y: float,
        radius: float,
        color_hex: str,
        alpha: float,
    ) -> None:
        radius = max(1.0, radius)
        color = QColor(color_hex)
        gradient = QRadialGradient(center_x, center_y, radius)
        start = QColor(color)
        start.setAlphaF(alpha)
        middle = QColor(color)
        middle.setAlphaF(alpha * 0.32)
        end = QColor(color)
        end.setAlphaF(0.0)
        gradient.setColorAt(0.0, start)
        gradient.setColorAt(0.45, middle)
        gradient.setColorAt(1.0, end)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(
            QRectF(
                center_x - radius,
                center_y - radius,
                radius * 2,
                radius * 2,
            )
        )
