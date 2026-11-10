"""顶部导航条：选中页展开为「图标 + 文字」胶囊，其余收缩为图标圆形。

设计取向（与磨砂玻璃风格一致）：
- 导航条占满整行（容器定宽），项从左依次排列：切页时左端点不动，只有胶囊的
  右边界推出、旧胶囊的右边界压入，避免整条左右「呼吸」；
- 整行较长，底条用小圆角 + 更弱的一档填充/高光，像贴着顶部的工具带而不是药丸；
- 当前页占一个胶囊，其余页只留 32px 圆形图标位，节省横向空间；悬停用 tooltip 补全文字；
- 项总宽超出可用宽度时出现左右翻页箭头，一次跨 3 个项（不超过一屏），
  未来页面变多不必改结构。

控件全部自绘：Qt 没有「宽度随选中变化」的现成控件，用子控件做布局会在动画
期间反复触发布局计算，自绘只需一次宽度插值，性能与观感都更可控。
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from gui.theme.background import BackgroundWidget
from gui.theme.blur import blur_image
from gui.theme.tokens import DesignTokens, tokens_for

__all__ = ["NavBar"]

#: 展开动画时长（毫秒），与下拉/悬停的节奏对齐。
_EXPAND_DURATION_MS = 220
#: 翻页滚动时长（毫秒）。
_SCROLL_DURATION_MS = 260
#: 图标与文字的间距。
_ICON_TEXT_GAP = 6.0
#: 翻页时内容区左右边缘的渐隐宽度。
_EDGE_FADE = 14.0
#: 点击翻页箭头一次跨过的项数。
_PAGE_STEP_ITEMS = 3


class NavBar(QWidget):
    """分段式页面导航条。

    Args:
        tokens: 初始设计令牌。
        parent: 父控件。

    Attributes:
        currentChanged: 当前页变化时发出，参数为页面索引。
    """

    currentChanged = Signal(int)

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens or tokens_for("light")
        self._icons: list[str] = []
        self._titles: list[str] = []
        self._current = 0
        self._widths: list[float] = []
        self._hover = -1
        self._offset = 0.0
        self._press_item = -1
        self._press_page = 0
        self._expand_anim: QVariantAnimation | None = None
        self._scroll_anim: QVariantAnimation | None = None
        self._backdrop: QImage | None = None
        self._backdrop_key: tuple[int, int, int, int, int] | None = None
        self._bare = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_bare(self, bare: bool) -> None:
        """是否去掉玻璃底条，只保留导航项（嵌进自绘标题栏时使用）。

        标题栏本身已有底色与分隔线，再叠一条玻璃条会形成"条中条"。
        """
        if bare == self._bare:
            return
        self._bare = bare
        self.update()

    # ------------------------------------------------------------------ 数据

    def add_item(self, icon: str, title: str) -> None:
        """追加一个导航项。

        Args:
            icon: 图标键（``settings`` / ``sample``）。
            title: 页面标题（同时用于 tooltip）。
        """
        self._icons.append(icon)
        self._titles.append(title)
        self._widths = self._target_widths()
        self._refresh_geometry()

    def set_current(self, index: int, *, animate: bool = True) -> None:
        """切换当前页。

        Args:
            index: 目标页面索引。
            animate: 是否播放宽度过渡动画。
        """
        if not self._icons:
            return
        index = max(0, min(index, len(self._icons) - 1))
        if index == self._current:
            self._ensure_visible(index)
            return
        start = list(self._widths) or self._target_widths()
        self._current = index
        self._widths = start
        if animate:
            self._start_expand_animation(start)
        else:
            self._widths = self._target_widths()
        self._ensure_visible(index)
        self._refresh_geometry()
        self.update()
        self.currentChanged.emit(index)

    def current(self) -> int:
        """当前页索引。"""
        return self._current

    def count(self) -> int:
        """导航项数量。"""
        return len(self._icons)

    def needs_paging(self) -> bool:
        """当前宽度下是否需要左右翻页。"""
        return self._paging()

    def target_widths(self) -> list[float]:
        """各项的目标宽度（选中项为胶囊宽，其余为圆形宽，单位像素）。"""
        return self._target_widths()

    def set_titles(self, titles: list[str]) -> None:
        """语言切换后更新各项文字（会按新文字重算胶囊宽度）。"""
        if not titles:
            return
        self._titles = list(titles)
        self._widths = self._target_widths()
        self._refresh_geometry()
        self.update()

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """切换主题令牌（重建玻璃缓存与几何）。"""
        self._tokens = tokens
        self._backdrop = None
        self._backdrop_key = None
        self._widths = self._target_widths()
        self._refresh_geometry()
        self.update()

    # ------------------------------------------------------------ 尺寸与几何

    def sizeHint(self) -> QSize:
        """理想尺寸：容纳全部项（含圆角底条内边距）。"""
        if not self._icons:
            return QSize(0, self._bar_height())
        total = self._total_width(self._target_widths(), self._gap, self._pad)
        return QSize(int(total), self._bar_height())

    def minimumSizeHint(self) -> QSize:
        """最窄可用尺寸：至少放得下一个收起状态项与一个翻页箭头区。"""
        collapsed = self._collapsed_width()
        return QSize(int(collapsed + self._pad * 2), self._bar_height())

    def _bar_height(self) -> int:
        return int(self._item_height + self._pad * 2)

    @property
    def _pad(self) -> float:
        return float(self._tokens.metrics.nav_padding)

    @property
    def _item_height(self) -> float:
        return float(self._tokens.metrics.nav_height)

    @property
    def _gap(self) -> float:
        return float(self._tokens.metrics.nav_gap)

    @property
    def _arrow_width(self) -> float:
        return float(self._tokens.metrics.nav_arrow_width)

    def _collapsed_width(self) -> float:
        return self._item_height

    def _expanded_width(self, title: str) -> float:
        icon = float(self._tokens.metrics.nav_icon)
        inner_pad = float(self._tokens.metrics.nav_item_padding)
        text_width = float(QFontMetrics(self.font()).horizontalAdvance(title))
        return inner_pad * 2 + icon + _ICON_TEXT_GAP + text_width

    def _target_widths(self) -> list[float]:
        widths = []
        for index, title in enumerate(self._titles):
            if index == self._current:
                widths.append(self._expanded_width(title))
            else:
                widths.append(self._collapsed_width())
        return widths

    @staticmethod
    def _total_width(widths: list[float], gap: float = 0.0, pad: float = 0.0) -> float:
        if not widths:
            return 0.0
        return sum(widths) + gap * (len(widths) - 1) + pad * 2

    def _total(self) -> float:
        return self._total_width(self._widths, self._gap, self._pad)

    def _target_total(self) -> float:
        return self._total_width(self._target_widths(), self._gap, self._pad)

    def _paging(self) -> bool:
        """项总宽放不下时进入翻页模式。"""
        if not self._icons:
            return False
        return self._target_total() > self.width() + 0.5

    def _content_span(self) -> tuple[float, float, bool]:
        """返回内容区的左右边界与是否处于翻页模式。"""
        paging = self._paging()
        left = self._pad
        if paging:
            left += self._arrow_width + self._gap
            right = self.width() - self._pad - self._arrow_width - self._gap
        else:
            right = self.width() - self._pad
        return left, right, paging

    def _max_offset(self) -> float:
        left, right, paging = self._content_span()
        if not paging:
            return 0.0
        content = self._total_width(self._target_widths(), self._gap)
        return max(0.0, content - (right - left))

    def _item_rects(self) -> list[QRectF]:
        left, _right, _paging = self._content_span()
        x = left - self._offset
        rects = []
        for width in self._widths:
            rects.append(QRectF(x, self._pad, width, self._item_height))
            x += width + self._gap
        return rects

    def _refresh_geometry(self) -> None:
        self.updateGeometry()
        self.update()

    def _ensure_visible(self, index: int) -> None:
        """让指定项完整落在可视区内（翻页模式下的必要滚动）。

        这里用「目标宽度」算布局：切换瞬间动画还没开始，按动画中的宽度算会偏移。
        """
        if not self._paging() or index < 0:
            return
        left, right, _paging = self._content_span()
        targets = self._target_widths()
        start = sum(w + self._gap for w in targets[:index])
        width = targets[index] if index < len(targets) else 0.0
        visible = right - left
        start_screen = left + start - self._offset
        if width >= visible or start_screen < left:
            self._scroll_to(start)
        elif start_screen + width > right:
            self._scroll_to(start + width - visible)

    def _scroll_to(self, offset: float) -> None:
        offset = max(0.0, min(offset, self._max_offset()))
        if abs(offset - self._offset) < 0.5:
            return
        if self._scroll_anim is not None:
            self._scroll_anim.stop()
        start = self._offset
        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(offset)
        anim.setDuration(_SCROLL_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_value(value: object) -> None:
            self._offset = float(value)  # type: ignore[arg-type]
            self.update()

        anim.valueChanged.connect(_on_value)
        self._scroll_anim = anim
        anim.start()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._backdrop = None
        self._backdrop_key = None
        self._offset = min(self._offset, self._max_offset())

    # ------------------------------------------------------------------ 动画

    def _start_expand_animation(self, start: list[float]) -> None:
        targets = self._target_widths()
        if len(start) != len(targets):
            self._widths = targets
            return
        if self._expand_anim is not None:
            self._expand_anim.stop()
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(_EXPAND_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_value(value: object) -> None:
            ratio = float(value)  # type: ignore[arg-type]
            self._widths = [
                s + (t - s) * ratio for s, t in zip(start, targets, strict=False)
            ]
            self.update()

        def _on_finished() -> None:
            self._widths = targets
            self.update()

        anim.valueChanged.connect(_on_value)
        anim.finished.connect(_on_finished)
        self._expand_anim = anim
        anim.start()

    # ------------------------------------------------------------------ 绘制

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            if not self._bare:
                self._paint_glass(painter)
            left, right, paging = self._content_span()
            painter.save()
            painter.setClipRect(
                QRectF(left, 0.0, max(0.0, right - left), float(self.height()))
            )
            if paging:
                painter.drawImage(QPoint(0, 0), self._items_layer())
            else:
                for index, rect in enumerate(self._item_rects()):
                    self._paint_item(painter, index, rect)
            painter.restore()
            if paging:
                self._paint_arrows(painter, left, right)
        finally:
            painter.end()

    def _items_layer(self) -> QImage:
        """把导航项画到离屏图层，并对翻页时的左右边缘做渐隐。

        翻页滚动中边缘必然出现半个图标，直接硬裁会像切坏了；改成离屏绘制后
        用 ``DestinationIn`` 擦出渐隐，玻璃底条不受影响。
        """
        dpr = self.devicePixelRatioF()
        layer = QImage(
            int(self.width() * dpr),
            int(self.height() * dpr),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for index, rect in enumerate(self._item_rects()):
                self._paint_item(painter, index, rect)
        finally:
            painter.end()

        left, right, _paging = self._content_span()
        fade = _EDGE_FADE
        mask = QPainter(layer)
        try:
            mask.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationIn
            )
            if self._offset > 0.5:
                gradient = QLinearGradient(
                    QPointF(left, 0.0), QPointF(left + fade, 0.0)
                )
                gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
                gradient.setColorAt(1.0, QColor(0, 0, 0, 255))
                mask.fillRect(QRectF(left, 0.0, fade, float(self.height())), gradient)
            if self._offset < self._max_offset() - 0.5:
                gradient = QLinearGradient(
                    QPointF(right - fade, 0.0), QPointF(right, 0.0)
                )
                gradient.setColorAt(0.0, QColor(0, 0, 0, 255))
                gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
                mask.fillRect(
                    QRectF(right - fade, 0.0, fade, float(self.height())),
                    gradient,
                )
        finally:
            mask.end()
        return layer

    def _paint_glass(self, painter: QPainter) -> None:
        """绘制毛玻璃底条。

        导航条占满整行时横向很长，若用卡片那套饱满的填充与高光，会变成一片
        压不住字的白玻璃；这里改用更弱的一档填充/高光与小圆角，让它更像一条
        贴着窗口顶部的工具带，而不是悬浮药丸。
        """
        palette = self._tokens.palette
        metrics = self._tokens.metrics
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = float(metrics.radius_card)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        backdrop = self._backdrop_image()
        if backdrop is not None:
            painter.save()
            painter.setClipPath(path)
            painter.drawImage(rect.topLeft(), backdrop)
            painter.restore()

        fill = QColor(palette.card_fill)
        fill.setAlphaF(palette.nav_fill_alpha)
        painter.fillPath(path, fill)

        painter.save()
        painter.setClipPath(path)
        highlight = QColor(255, 255, 255)
        highlight.setAlphaF(palette.nav_highlight_alpha)
        fade = QColor(255, 255, 255)
        fade.setAlphaF(0.0)
        gradient = QLinearGradient(
            rect.topLeft(),
            QPointF(rect.left(), rect.top() + rect.height() * 0.5),
        )
        gradient.setColorAt(0.0, highlight)
        gradient.setColorAt(1.0, fade)
        painter.fillRect(rect, gradient)
        painter.restore()

        border = QColor(palette.card_border)
        border.setAlphaF(self._tokens.palette.nav_border_alpha)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _paint_item(self, painter: QPainter, index: int, rect: QRectF) -> None:
        palette = self._tokens.palette
        active = index == self._current
        hovered = index == self._hover and not active
        radius = rect.height() / 2.0

        if active or hovered:
            fill = QColor(palette.accent)
            fill.setAlphaF(
                palette.nav_active_alpha if active else palette.nav_hover_alpha
            )
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(path, fill)

        icon_color = QColor(
            palette.accent
            if active
            else (palette.text_secondary if hovered else palette.text_muted)
        )
        icon_size = float(self._tokens.metrics.nav_icon)
        inner_pad = float(self._tokens.metrics.nav_item_padding)
        icon_left = (
            rect.left() + inner_pad
            if active
            else rect.left() + (rect.width() - icon_size) / 2.0
        )
        icon_rect = QRectF(
            icon_left,
            rect.top() + (rect.height() - icon_size) / 2.0,
            icon_size,
            icon_size,
        )
        self._draw_icon(
            painter,
            self._icons[index] if index < len(self._icons) else "sample",
            icon_rect,
            icon_color,
        )

        if not active:
            return
        text_left = icon_rect.right() + _ICON_TEXT_GAP
        available = rect.right() - inner_pad - text_left
        if available <= 2.0:
            return
        painter.setPen(QColor(palette.accent))
        painter.setFont(self.font())
        painter.drawText(
            QRectF(text_left, rect.top(), available, rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._titles[index] if index < len(self._titles) else "",
        )

    def _draw_icon(
        self,
        painter: QPainter,
        kind: str,
        rect: QRectF,
        color: QColor,
    ) -> None:
        painter.save()
        pen = QPen(color, 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "settings":
            # 三条滑块：横线 + 位置上不同的圆点
            for ratio, dot_ratio in (
                (0.28, 0.28),
                (0.50, 0.70),
                (0.72, 0.44),
            ):
                y = rect.top() + rect.height() * ratio
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                cx = rect.left() + rect.width() * dot_ratio
                painter.setBrush(color)
                painter.drawEllipse(QPointF(cx, y), 2.1, 2.1)
                painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            # 两层错位方框：表示「示例页 / 版面」
            side = rect.width() * 0.66
            offset = rect.width() - side
            painter.drawRoundedRect(
                QRectF(
                    rect.left(),
                    rect.top(),
                    side,
                    side,
                ),
                2.4,
                2.4,
            )
            painter.drawRoundedRect(
                QRectF(
                    rect.left() + offset,
                    rect.top() + offset,
                    side,
                    side,
                ),
                2.4,
                2.4,
            )
        painter.restore()

    def _paint_arrows(self, painter: QPainter, left: float, right: float) -> None:
        size = self._item_height
        # 左箭头
        left_rect = QRectF(
            self._pad,
            self._pad,
            self._arrow_width,
            size,
        )
        right_rect = QRectF(
            self.width() - self._pad - self._arrow_width,
            self._pad,
            self._arrow_width,
            size,
        )
        self._paint_arrow(
            painter,
            left_rect,
            pointing_left=True,
            enabled=self._offset > 0.5,
        )
        self._paint_arrow(
            painter,
            right_rect,
            pointing_left=False,
            enabled=self._offset < self._max_offset() - 0.5,
        )

    def _paint_arrow(
        self,
        painter: QPainter,
        rect: QRectF,
        *,
        pointing_left: bool,
        enabled: bool,
    ) -> None:
        palette = self._tokens.palette
        color = QColor(palette.text_secondary if enabled else palette.text_muted)
        if not enabled:
            color.setAlphaF(0.45)
        center = rect.center()
        half = 2.8
        pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if pointing_left:
            painter.drawLine(
                QPointF(center.x() + half, center.y() - half),
                QPointF(center.x() - half, center.y()),
            )
            painter.drawLine(
                QPointF(center.x() - half, center.y()),
                QPointF(center.x() + half, center.y() + half),
            )
        else:
            painter.drawLine(
                QPointF(center.x() - half, center.y() - half),
                QPointF(center.x() + half, center.y()),
            )
            painter.drawLine(
                QPointF(center.x() + half, center.y()),
                QPointF(center.x() - half, center.y() + half),
            )

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

    # ------------------------------------------------------------------ 交互

    def _hit_test(self, pos: QPoint) -> tuple[str, int]:
        """命中测试，返回 ``("item", i)`` / ``("page", ±1)`` / ``("none", -1)``。"""
        left, right, paging = self._content_span()
        if paging:
            left_rect = QRectF(
                self._pad, self._pad, self._arrow_width, self._item_height
            )
            right_rect = QRectF(
                self.width() - self._pad - self._arrow_width,
                self._pad,
                self._arrow_width,
                self._item_height,
            )
            if left_rect.contains(QPointF(pos)):
                return ("page", -1)
            if right_rect.contains(QPointF(pos)):
                return ("page", 1)
        for index, rect in enumerate(self._item_rects()):
            if not rect.intersects(
                QRectF(left, 0.0, right - left, float(self.height()))
            ):
                continue
            if rect.contains(QPointF(pos)):
                return ("item", index)
        return ("none", -1)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        kind, index = self._hit_test(event.position().toPoint())
        hover = index if kind == "item" else -1
        if hover != self._hover:
            self._hover = hover
            self.update()
            if hover >= 0 and hover != self._current:
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    self._titles[hover],
                    self,
                )
            else:
                QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = -1
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        kind, index = self._hit_test(event.position().toPoint())
        self._press_item = index if kind == "item" else -1
        self._press_page = index if kind == "page" else 0
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        kind, index = self._hit_test(event.position().toPoint())
        if kind == "item" and index == self._press_item and index >= 0:
            self.set_current(index)
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        elif kind == "page" and index == self._press_page:
            self._page_by(index)
        self._press_item = -1
        self._press_page = 0
        super().mouseReleaseEvent(event)

    def _first_visible(self) -> int:
        """最左侧仍可见（哪怕只露出一部分）的项索引。"""
        starts = 0.0
        for index, width in enumerate(self._target_widths()):
            if starts + width > self._offset + 0.5:
                return index
            starts += width + self._gap
        return max(0, self.count() - 1)

    def _item_start(self, index: int) -> float:
        """指定项在内容坐标系里的起点（未滚动时的 x）。"""
        starts = 0.0
        for current, width in enumerate(self._target_widths()):
            if current == index:
                return starts
            starts += width + self._gap
        return starts

    def page_target(self, direction: int) -> float:
        """点击翻页箭头后应滚动到的偏移量（正数向右）。

        Args:
            direction: ``1`` 向右、``-1`` 向左。

        Returns:
            目标偏移量（已按「一次不超过一屏」与内容总宽做钳制）。
        """
        if not self._icons or direction == 0:
            return 0.0
        first = self._first_visible()
        target_index = first + direction * _PAGE_STEP_ITEMS
        target_index = max(0, min(target_index, self.count() - 1))
        offset = self._item_start(target_index)
        left, right, _paging = self._content_span()
        visible = right - left
        # 一次最多滚一屏：项宽很大（长标题胶囊）时不会跳过头
        offset = min(offset, self._offset + visible)
        offset = max(offset, self._offset - visible)
        return min(offset, self._max_offset())

    def _page_by(self, direction: int) -> None:
        """按 3 个项翻页（供左右箭头调用）。"""
        self._scroll_to(self.page_target(direction))

    def _snap_backward(self, offset: float) -> float:
        """把偏移量向左对齐到最近的项起点（0 也是合法起点）。"""
        starts = 0.0
        best = 0.0
        for width in self._target_widths():
            if starts <= offset + 0.5:
                best = starts
            starts += width + self._gap
        return best

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._paging():
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:
                target = max(
                    0.0,
                    min(self._offset - delta * 0.5, self._max_offset()),
                )
                self._scroll_to(self._snap_backward(target))
                event.accept()
                return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -1 if key == Qt.Key.Key_Left else 1
            self.set_current(self._current + step)
            event.accept()
            return
        super().keyPressEvent(event)
