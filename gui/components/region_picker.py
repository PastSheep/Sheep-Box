"""屏幕选区覆盖层。

只产出坐标，不截图：选择结果同时给出屏幕物理矩形、客户区像素区域与归一化区域
三种形态，调用方按自己的口径取用（截图本身走 ``service.capture``）。

实现要点：

- 覆盖所有显示器并集，半透明遮罩 + 悬停窗口高亮；
- 拖拽拉框时实时显示物理尺寸；松开确认，``Esc`` 取消；
- 距窗口边缘 8px 吸附，拖拽不足 4px 视为「单击选整窗」；
- 产出前用 ``region_from_screen`` 换算，越界部分被钳制。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from common.exceptions import CaptureError
from service.capture import get_window_info, hwnd_from_point, region_from_screen
from service.capture.models import CaptureRegion, NormalizedRegion

__all__ = ["PickResult", "RegionPicker"]

_SNAP_PHYSICAL_PX = 8
_CLICK_PHYSICAL_PX = 4
_MASK_ALPHA = 102  # 40% 黑
_ACCENT = "#3B82F6"


@dataclass(frozen=True)
class PickResult:
    """一次选区的结果。

    Attributes:
        hwnd: 目标窗口句柄。
        screen_rect: 选区的屏幕物理矩形 ``(left, top, width, height)``。
        client_region: 客户区口径的像素区域。
        normalized_region: 相对客户区的比例区域（0~1）。
    """

    hwnd: int
    screen_rect: tuple[int, int, int, int]
    client_region: CaptureRegion
    normalized_region: NormalizedRegion


def _physical_point(point: QPoint) -> tuple[int, int]:
    """把 Qt 逻辑坐标换算成屏幕物理像素。

    以落点所在屏幕为基准，用该屏的 ``devicePixelRatio`` 换算；多屏混合缩放时
    该结果按「逻辑原点 × 比例」近似物理原点，偏差不超过系统缩放取整误差。

    Args:
        point: 全局逻辑坐标。

    Returns:
        物理坐标 ``(x, y)``。
    """
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    if screen is None:  # pragma: no cover - 无屏幕时 Qt 本身不可用
        return point.x(), point.y()
    geometry = screen.geometry()
    ratio = screen.devicePixelRatio()
    x = round((point.x() - geometry.x()) * ratio) + round(geometry.x() * ratio)
    y = round((point.y() - geometry.y()) * ratio) + round(geometry.y() * ratio)
    return x, y


class RegionPicker(QWidget):
    """全屏覆盖的选区组件。

    Signals:
        picked: 选中完成，参数为 :class:`PickResult`。
        cancelled: 用户取消（Esc、右键或选区为空）。
    """

    picked = Signal(object)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._origin: tuple[int, int] | None = None
        self._current: tuple[int, int] | None = None
        self._hover: tuple[int, int, int, int] | None = None
        self._hover_hwnd: int = 0

    def start(self) -> None:
        """覆盖虚拟桌面并显示，开始接收鼠标。"""
        union = QRect()
        for screen in QGuiApplication.screens():
            union = union.united(screen.geometry())
        self.setGeometry(union)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # ---------------------------------------------------------------- 绘制

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制遮罩、高亮与选框。"""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        painter.fillRect(self.rect(), QColor(0, 0, 0, _MASK_ALPHA))

        if self._hover is not None:
            hover_rect = self._to_local(self._hover)
            painter.setPen(QPen(QColor(_ACCENT), 1, Qt.PenStyle.DashLine))
            painter.drawRect(hover_rect)

        selection = self._selection_physical()
        if selection is not None:
            local = self._to_local(selection)
            painter.fillRect(local, QColor(0, 0, 0, 0))
            painter.setPen(QPen(QColor(_ACCENT), 2, Qt.PenStyle.SolidLine))
            painter.drawRect(local)
            self._draw_size_label(painter, local, selection)

        painter.setPen(QColor(255, 255, 255, 220))
        hint = self.tr("Click a window, or drag to select a region (Esc to cancel)")
        painter.drawText(
            QRectF(self.rect()).adjusted(24, 24, -24, -24),
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter),
            hint,
        )

    def _draw_size_label(
        self, painter: QPainter, local: QRect, physical: tuple[int, int, int, int]
    ) -> None:
        """在选框上方绘制物理尺寸标签。"""
        text = f"{physical[2]} × {physical[3]}"
        rect = QRect(local.left(), max(local.top() - 26, 0), max(local.width(), 80), 22)
        painter.fillRect(rect, QColor(0, 0, 0, 160))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    def _to_local(self, physical: tuple[int, int, int, int]) -> QRect:
        """把物理矩形换算成控件内的逻辑矩形。"""
        ratio = self.devicePixelRatio()
        union_x = self.geometry().x() * ratio
        union_y = self.geometry().y() * ratio
        return QRect(
            round((physical[0] - union_x) / ratio),
            round((physical[1] - union_y) / ratio),
            round(physical[2] / ratio),
            round(physical[3] / ratio),
        )

    def _selection_physical(self) -> tuple[int, int, int, int] | None:
        """当前拖拽形成的物理矩形。"""
        if self._origin is None or self._current is None:
            return None
        x0, x1 = sorted((self._origin[0], self._current[0]))
        y0, y1 = sorted((self._origin[1], self._current[1]))
        return x0, y0, x1 - x0, y1 - y0

    # ---------------------------------------------------------------- 交互

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """更新悬停窗口或拖拽选框。"""
        physical = _physical_point(event.globalPosition().toPoint())
        if self._origin is not None:
            self._current = physical
            self.update()
            return

        hwnd = hwnd_from_point(*physical)
        if hwnd == self._hover_hwnd:
            return
        self._hover_hwnd = hwnd
        self._hover = None
        if hwnd:
            try:
                info = get_window_info(hwnd)
            except CaptureError:  # pragma: no cover - 查询失败的窗口直接忽略
                info = None
            if info is not None:
                self._hover = (
                    info.client_origin[0],
                    info.client_origin[1],
                    info.screen_width,
                    info.screen_height,
                )
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键开始拖拽；右键取消。"""
        if event.button() == Qt.MouseButton.RightButton:
            self._finish_cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._origin = _physical_point(event.globalPosition().toPoint())
        self._current = self._origin
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """松开左键：拖拽不足阈值时选整窗，否则选拖出的区域。"""
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        selection = self._selection_physical()
        self._origin = None
        self._current = None
        if selection is None:
            self._finish_cancel()
            return
        if selection[2] < _CLICK_PHYSICAL_PX or selection[3] < _CLICK_PHYSICAL_PX:
            self._finish_window()
            return
        self._finish_region(self._apply_snap(selection))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Esc 取消。"""
        if event.key() == Qt.Key.Key_Escape:
            self._finish_cancel()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- 结果

    def _apply_snap(self, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """把选框的四条边吸附到悬停窗口的客户区边缘。

        Args:
            rect: 物理矩形。

        Returns:
            吸附后的矩形。
        """
        if self._hover is None:
            return rect
        hx, hy, hw, hh = self._hover
        left, top, width, height = rect
        right, bottom = left + width, top + height

        snap_left = hx if abs(left - hx) <= _SNAP_PHYSICAL_PX else left
        snap_top = hy if abs(top - hy) <= _SNAP_PHYSICAL_PX else top
        snap_right = hx + hw if abs(right - (hx + hw)) <= _SNAP_PHYSICAL_PX else right
        snap_bottom = (
            hy + hh if abs(bottom - (hy + hh)) <= _SNAP_PHYSICAL_PX else bottom
        )
        if snap_right <= snap_left or snap_bottom <= snap_top:
            return rect
        return snap_left, snap_top, snap_right - snap_left, snap_bottom - snap_top

    def _finish_window(self) -> None:
        """把悬停窗口的整个客户区作为选区。"""
        if not self._hover_hwnd or self._hover is None:
            self._finish_cancel()
            return
        self._finish_region(self._hover, hwnd=self._hover_hwnd)

    def _finish_region(
        self,
        rect: tuple[int, int, int, int],
        *,
        hwnd: int | None = None,
    ) -> None:
        """换算并发出选区结果。"""
        target_hwnd = hwnd or self._hover_hwnd
        if not target_hwnd:
            self._finish_cancel()
            return
        try:
            info = get_window_info(target_hwnd)
            region = region_from_screen(info, rect)
        except CaptureError:
            self._finish_cancel()
            return
        if region.empty or info.client_width <= 0 or info.client_height <= 0:
            self._finish_cancel()
            return
        normalized = NormalizedRegion(
            region.x / info.client_width,
            region.y / info.client_height,
            region.width / info.client_width,
            region.height / info.client_height,
        )
        self.picked.emit(PickResult(target_hwnd, rect, region, normalized))
        self.close()

    def _finish_cancel(self) -> None:
        """发出取消信号并关闭。"""
        self.cancelled.emit()
        self.close()
