"""利用率着色的渐变锚点编辑控件。

交互模型（「位置 → 颜色」的可视化编辑）：

- 轨道横向表示 0~100%，本身就是当前渐变，所见即所得；
- **左键点击轨道空白处**：在该位置新增锚点，颜色取该位置渐变的采样值；
- **左键按住节点拖动**：改变阈值位置，节点旁跟随显示百分比标签（标签默认在
  节点上方，相邻标签会挤到一起时自动上下交错）；
- **右键点击锚点**：弹出浮层，内含调色板、自定义颜色与删除；
- **两端 0% 与 100% 固定**：不能拖动、不能删除，只能改颜色；配置里缺端点时自动补上；
- 中间锚点至少保留 2 个（少于 2 个无法构成渐变），删除会在下限处被拒绝。

控件只持有 ``[(位置, #RRGGBB), ...]``，不含持久化逻辑；谁写配置由调用方决定。
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.components.usage_gradient import UsageGradient
from gui.theme.style import rgba
from gui.theme.tokens import DesignTokens, tokens_for

__all__ = ["GradientStopsControl"]

#: 控件总高度（上下两排标签 + 节点 + 轨道）
CONTROL_HEIGHT = 62
#: 轨道高度：刻意比节点直径小，让节点像"卡在细线上的珠子"
_TRACK_HEIGHT = 6
#: 左右留白，保证首尾节点的光晕不被裁掉
_MARGIN_X = 14
#: 节点半径（绘制用），直径 12 > 轨道 6
_NODE_RADIUS = 6.0
#: 端点菱形的对角半径（菱形长对角线 14）
_ENDPOINT_RADIUS = 7.0
#: 命中容差（像素）
_HIT_SLOP = 4.0
#: 标签与节点边缘的间隙
_LABEL_GAP = 5.0
#: 相邻标签之间的最小水平间隙，小于它就上下错开
_LABEL_SPACING = 10.0
#: 锚点之间的最小位置差（百分比），同时约束拖动与新增
_MIN_GAP_PERCENT = 2.0
#: 判定「端点」的位置容差（百分比）
_FIXED_EPS = 0.5
#: 调色板预设色（按暖 → 冷排列，覆盖常见压力语义）
_PRESET_COLORS = (
    "#17A05E",
    "#7BC043",
    "#E0A008",
    "#E8752B",
    "#D94A4A",
    "#B44BD6",
    "#2F6FEB",
    "#00A896",
)


class _AnchorPopup(QWidget):
    """锚点编辑浮层：调色板 + 自定义颜色 + 删除。

    Signals:
        color_selected: 用户选定颜色，参数为 ``#rrggbb``。
        delete_requested: 用户点击删除。
    """

    color_selected = Signal(str)
    delete_requested = Signal()

    def __init__(
        self,
        tokens: DesignTokens,
        current_color: str,
        can_delete: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self._tokens = tokens
        # 无边框 + 透明背景，圆角才不会被系统窗口底色切出直角黑边
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        body = QFrame(self)
        body.setObjectName("AnchorPopupBody")
        grid = QGridLayout(body)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(6)
        for index, color in enumerate(_PRESET_COLORS):
            swatch = QPushButton(body)
            swatch.setFixedSize(22, 22)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setStyleSheet(
                f"QPushButton {{ background: {color}; border: 1px solid "
                f"{rgba(tokens.palette.menu_border, 0.2)}; border-radius: 5px; }}"
                f"QPushButton:hover {{ border: 2px solid {tokens.palette.accent}; }}"
            )
            swatch.clicked.connect(
                lambda _checked=False, value=color: self._pick(value)
            )
            grid.addWidget(swatch, index // 4, index % 4)

        self._custom = QPushButton(self.tr("Custom"), body)
        self._custom.setCursor(Qt.CursorShape.PointingHandCursor)
        self._custom.clicked.connect(self._open_color_dialog)
        grid.addWidget(self._custom, 2, 0, 1, 4)

        self._delete = QPushButton(self.tr("Delete"), body)
        self._delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete.setEnabled(can_delete)
        self._delete.clicked.connect(self._request_delete)
        grid.addWidget(self._delete, 3, 0, 1, 4)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body)

        self._body = body
        self._current = current_color
        self.apply_tokens(tokens)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow_color = QColor(tokens.palette.shadow)
        shadow_color.setAlphaF(tokens.palette.shadow_alpha)
        shadow.setColor(shadow_color)
        body.setGraphicsEffect(shadow)

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """按主题刷新浮层配色。"""
        self._tokens = tokens
        palette = tokens.palette
        metrics = tokens.metrics
        self._body.setStyleSheet(
            f"QFrame#AnchorPopupBody {{ background: {palette.menu_fill}; "
            f"border: 1px solid "
            f"{rgba(palette.menu_border, palette.menu_border_alpha)}; "
            f"border-radius: {metrics.radius_menu}px; }}"
        )
        self._custom.setStyleSheet(
            f"QPushButton {{ color: {palette.text_primary}; background: transparent; "
            f"border: none; padding: 4px 6px; border-radius: {metrics.radius_field}px; "
            f"font-size: {metrics.font_body}px; }}"
            f"QPushButton:hover {{ background: "
            f"{rgba(palette.menu_border, palette.menu_hover_alpha)}; }}"
        )
        self._delete.setStyleSheet(
            f"QPushButton {{ color: {palette.text_secondary}; background: transparent; "
            f"border: none; padding: 4px 6px; border-radius: {metrics.radius_field}px; "
            f"font-size: {metrics.font_body}px; }}"
            f"QPushButton:hover:enabled {{ background: "
            f"{rgba(palette.accent, palette.menu_hover_alpha)}; }}"
        )

    def _pick(self, color: str) -> None:
        """选中预设色并关闭浮层。"""
        self.color_selected.emit(color)
        self.close()

    def _open_color_dialog(self) -> None:
        """打开系统取色器；选定后立即应用。"""
        selected = QColorDialog.getColor(QColor(self._current), self, self.tr("Color"))
        if selected.isValid():
            self.color_selected.emit(selected.name())
        self.close()

    def _request_delete(self) -> None:
        """请求删除当前锚点。"""
        self.delete_requested.emit()
        self.close()


class GradientStopsControl(QWidget):
    """渐变锚点编辑条：左键加点、右键改色或删除。

    Signals:
        stops_changed: 锚点发生变化，参数为 ``[(位置百分比, #rrggbb), ...]``
            （按位置升序）。
    """

    stops_changed = Signal(list)

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        stops: Sequence[tuple[float, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens or tokens_for("light")
        self._stops: list[tuple[float, str]] = self._normalize(
            stops
            if stops is not None
            else [
                (0.0, "#17A05E"),
                (50.0, "#E0A008"),
                (80.0, "#D94A4A"),
                (100.0, "#D94A4A"),
            ]
        )
        self._gradient = UsageGradient(self._stops)
        self._popup: _AnchorPopup | None = None
        self._active_index: int | None = None
        self._dragging: int | None = None
        self._drag_offset = 0.0
        self._drag_moved = False
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setMinimumWidth(160)
        # 悬停时也要拿到 move 事件，用于切换抓手光标
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ------------------------------------------------------------ 对外接口

    def stops(self) -> list[tuple[float, str]]:
        """当前锚点（按位置升序）。"""
        return list(self._stops)

    def set_stops(self, stops: Sequence[tuple[float, str]]) -> None:
        """外部设置锚点（如配置重载 / 恢复默认），不触发 ``stops_changed``。

        端点会被自动补齐：缺少 0 或 100 时按最近锚点的颜色补上，保证两端永远存在。

        Args:
            stops: ``[(位置, #RRGGBB), ...]``。
        """
        self._stops = self._normalize(stops)
        self._gradient = UsageGradient(self._stops)
        self.update()

    # ------------------------------------------------------------ 锚点整理

    @staticmethod
    def _normalize(
        stops: Sequence[tuple[float, str]],
    ) -> list[tuple[float, str]]:
        """排序、截断到 0~100、补齐两端并去掉重合锚点。

        两端锚点必须存在（状态栏渐变需要覆盖 0% 与 100%）：缺失时用最靠近的一端
        的颜色补齐，这样用户改端色也能保持。
        """
        items: list[tuple[float, str]] = sorted(
            ((max(0.0, min(100.0, float(at))), str(color)) for at, color in stops),
            key=lambda stop: stop[0],
        )
        if not items:
            return [(0.0, "#17A05E"), (100.0, "#D94A4A")]
        if items[0][0] > 0.0:
            items.insert(0, (0.0, items[0][1]))
        if items[-1][0] < 100.0:
            items.append((100.0, items[-1][1]))
        unique: list[tuple[float, str]] = []
        for at, color in items:
            if unique and abs(at - unique[-1][0]) < _FIXED_EPS:
                continue
            unique.append((at, color))
        return unique

    def _is_endpoint(self, index: int) -> bool:
        """该锚点是否是固定的 0% / 100% 端点。"""
        at = self._stops[index][0]
        return at <= _FIXED_EPS or at >= 100.0 - _FIXED_EPS

    def _neighbor_bounds(self, index: int) -> tuple[float, float]:
        """拖动时允许的活动范围（不越过左右邻居，也不挤出端点）。"""
        low = self._stops[index - 1][0] + _MIN_GAP_PERCENT if index > 0 else 0.0
        high = (
            self._stops[index + 1][0] - _MIN_GAP_PERCENT
            if index + 1 < len(self._stops)
            else 100.0
        )
        if low > high:  # 空间不足时退回中点，避免上下界反转
            middle = (self._stops[index - 1][0] + self._stops[index + 1][0]) / 2.0
            return middle, middle
        return low, high

    @staticmethod
    def _format_percent(at: float) -> str:
        """锚点位置 → 标签文本（整数不带小数，其余保留 1 位）。"""
        if abs(at - round(at)) < 0.05:
            return f"{round(at)}%"
        return f"{at:.1f}%"

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """主题切换时刷新配色（浮层若开着同步更新）。"""
        self._tokens = tokens
        if self._popup is not None:
            self._popup.apply_tokens(tokens)
        self.update()

    def retranslate_ui(self) -> None:
        """重设浮层文案（语言切换后调用，浮层按需重建）。"""
        if self._popup is not None:
            self._popup.close()
            self._popup = None

    # ------------------------------------------------------------ 几何

    def _track_rect(self) -> QRectF:
        """轨道矩形（横向铺满，垂直居中）。"""
        return QRectF(
            _MARGIN_X,
            (self.height() - _TRACK_HEIGHT) / 2.0,
            max(1.0, self.width() - 2 * _MARGIN_X),
            float(_TRACK_HEIGHT),
        )

    def _x_for(self, percent: float) -> float:
        """位置百分比 → 轨道上的 x 坐标。"""
        track = self._track_rect()
        return track.left() + track.width() * max(0.0, min(100.0, percent)) / 100.0

    def _percent_for(self, x: float) -> float:
        """轨道上的 x 坐标 → 位置百分比。"""
        track = self._track_rect()
        if track.width() <= 0:
            return 0.0
        return max(0.0, min(100.0, (x - track.left()) / track.width() * 100.0))

    def _hit_node(self, pos: QPointF) -> int | None:
        """命中测试：离节点圆心足够近则返回其索引。"""
        center_y = self._track_rect().center().y()
        for index, (at, _color) in enumerate(self._stops):
            distance = (
                (pos.x() - self._x_for(at)) ** 2 + (pos.y() - center_y) ** 2
            ) ** 0.5
            if distance <= _NODE_RADIUS + _HIT_SLOP:
                return index
        return None

    # ------------------------------------------------------------ 交互

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键按下节点进入拖动、按在空白处加点；右键弹浮层。"""
        pos = event.position()
        index = self._hit_node(pos)
        if event.button() == Qt.MouseButton.RightButton:
            if index is not None:
                self._active_index = index
                self._show_popup(index, event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if index is not None:
            self._active_index = index
            if not self._is_endpoint(index):
                self._dragging = index
                self._drag_offset = pos.x() - self._x_for(self._stops[index][0])
                self._drag_moved = False
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
            return
        self._add_stop(self._percent_for(pos.x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """拖动节点：位置被邻居与端点夹住，实时重画但不写配置。"""
        if self._dragging is None:
            return
        percent = self._percent_for(event.position().x() - self._drag_offset)
        low, high = self._neighbor_bounds(self._dragging)
        percent = round(max(low, min(high, percent)), 1)
        at, color = self._stops[self._dragging]
        if percent != at:
            self._stops[self._dragging] = (percent, color)
            self._gradient = UsageGradient(self._stops)
            self._drag_moved = True
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """结束拖动；只有位置真正变过才对外广播（避免一次拖动刷十几次配置）。"""
        if self._dragging is None:
            super().mouseReleaseEvent(event)
            return
        moved = self._drag_moved
        self._dragging = None
        self._drag_moved = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()
        if moved:
            self._emit_changed()

    def _add_stop(self, percent: float) -> None:
        """在指定位置新增锚点，颜色取该位置渐变采样值；离已有锚点太近则忽略。"""
        snapped = round(percent, 1)
        if snapped <= _FIXED_EPS or snapped >= 100.0 - _FIXED_EPS:
            return
        if any(abs(at - snapped) < _MIN_GAP_PERCENT for at, _color in self._stops):
            return
        color = self._gradient.color_at(snapped).name()
        self._stops = sorted([*self._stops, (snapped, color)], key=lambda stop: stop[0])
        self._gradient = UsageGradient(self._stops)
        self.update()
        self._emit_changed()

    def _update_stop_color(self, index: int, color: str) -> None:
        """改色并重建渐变。"""
        if 0 <= index < len(self._stops):
            at, _old = self._stops[index]
            self._stops[index] = (at, color)
            self._gradient = UsageGradient(self._stops)
            self.update()
            self._emit_changed()

    def _delete_stop(self, index: int) -> None:
        """删除中间锚点；端点 0% / 100% 固定，不可删除。"""
        if not (0 <= index < len(self._stops)):
            return
        if self._is_endpoint(index) or len(self._stops) <= 2:
            return
        self._stops.pop(index)
        self._gradient = UsageGradient(self._stops)
        self.update()
        self._emit_changed()

    def _emit_changed(self) -> None:
        """对外广播当前锚点。"""
        self.stops_changed.emit([(at, color) for at, color in self._stops])

    def _show_popup(self, index: int, global_pos: QPoint) -> None:
        """在节点旁弹出编辑浮层。"""
        if self._popup is not None:
            self._popup.close()
        at, color = self._stops[index]
        popup = _AnchorPopup(
            self._tokens,
            color,
            can_delete=not self._is_endpoint(index) and len(self._stops) > 2,
            parent=self,
        )
        popup.color_selected.connect(
            lambda value, index=index: self._update_stop_color(index, value)
        )
        popup.delete_requested.connect(lambda index=index: self._delete_stop(index))
        self._popup = popup
        popup.adjustSize()
        anchor = self.mapToGlobal(QPoint(int(self._x_for(at)), 0))
        popup.move(anchor.x() - popup.width() // 2, anchor.y() + CONTROL_HEIGHT + 6)
        popup.show()

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制渐变轨道、锚点节点与跟随节点的百分比标签。"""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            track = self._track_rect()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                self._gradient.linear_gradient(track.topLeft(), track.topRight())
            )
            painter.drawRoundedRect(track, _TRACK_HEIGHT / 2.0, _TRACK_HEIGHT / 2.0)

            palette = self._tokens.palette
            center_y = track.center().y()

            font = painter.font()
            font.setPixelSize(self._tokens.metrics.font_caption)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            sides = self._label_sides(metrics)
            label_pen = QPen(QColor(palette.text_secondary))
            active_pen = QPen(QColor(palette.accent))

            border = QColor(palette.card_border)
            border.setAlphaF(0.9)
            for index, (at, color) in enumerate(self._stops):
                center = QPointF(self._x_for(at), center_y)
                if index == self._active_index:
                    ring = QColor(palette.accent)
                    ring.setAlphaF(0.28)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(ring)
                    halo = (
                        _ENDPOINT_RADIUS if self._is_endpoint(index) else _NODE_RADIUS
                    ) + 4.0
                    painter.drawEllipse(center, halo, halo)
                painter.setPen(QPen(border, 1.5))
                painter.setBrush(QColor(color))
                if self._is_endpoint(index):
                    # 端点画成菱形：位置固定，形状上也和可拖动的圆点区分开
                    painter.drawPolygon(
                        QPolygonF(
                            [
                                QPointF(center.x(), center.y() - _ENDPOINT_RADIUS),
                                QPointF(center.x() + _ENDPOINT_RADIUS, center.y()),
                                QPointF(center.x(), center.y() + _ENDPOINT_RADIUS),
                                QPointF(center.x() - _ENDPOINT_RADIUS, center.y()),
                            ]
                        )
                    )
                else:
                    painter.drawEllipse(center, _NODE_RADIUS, _NODE_RADIUS)

                text = self._format_percent(at)
                text_width = float(metrics.horizontalAdvance(text))
                text_height = float(metrics.height())
                left = min(
                    max(2.0, center.x() - text_width / 2.0),
                    max(2.0, self.width() - 2.0 - text_width),
                )
                top = (
                    center_y - _NODE_RADIUS - _LABEL_GAP - text_height
                    if sides[index] == 0
                    else center_y + _NODE_RADIUS + _LABEL_GAP
                )
                painter.setPen(active_pen if index == self._dragging else label_pen)
                painter.drawText(
                    QRectF(left, top, text_width, text_height),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                    text,
                )
        finally:
            painter.end()

    def _label_sides(self, metrics: QFontMetrics) -> list[int]:
        """给每个锚点分配标签位置：0 在上、1 在下。

        按 x 从左到右贪心排：默认放上排，与上一个上排标签挤到一起时改放下排；
        下排也挤时退回上排（密集区至少保证依次错开，而不是全部叠在一起）。
        """
        sides: list[int] = []
        last_right = [float("-inf"), float("-inf")]
        for at, _color in self._stops:
            width = float(metrics.horizontalAdvance(self._format_percent(at)))
            left = self._x_for(at) - width / 2.0
            side = 0
            if left < last_right[0] + _LABEL_SPACING:
                side = 1
                if left < last_right[1] + _LABEL_SPACING:
                    side = 0
            last_right[side] = left + width
            sides.append(side)
        return sides
