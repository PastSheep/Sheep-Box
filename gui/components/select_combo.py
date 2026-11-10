"""下拉选择控件：幽灵字段外观 + 自绘箭头 + 圆角弹层。

外观分「关闭态 / 悬停 / 展开」三态：
- 关闭态：近乎透明的填充 + 细边框，让玻璃卡片透上来（不切出白块）；
- 悬停：填充与边框略微加深，提示可点击；
- 展开：边框转为强调色，箭头翻转朝上。

弹层（popup）在 Qt 里是独立顶层窗口（``QComboBoxPrivateContainer``），默认带
窗口边框与直角，QSS 的圆角会被窗口裁掉。这里在弹出前把容器设为
``Frameless + Translucent``，圆角与内部衬距才能真正生效。

箭头不用 QSS 图片（无法随主题变色），用 ``QPainterPath`` 自绘 1.5px 细线。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from gui.theme.style import build_popup_stylesheet
from gui.theme.tokens import DesignTokens, tokens_for

__all__ = ["SelectComboBox"]

#: 弹层列表与容器的对象名（供 QSS 命中）。
POPUP_VIEW_NAME = "ComboPopupView"
POPUP_CONTAINER_NAME = "ComboPopupContainer"

#: 箭头中心距控件右边缘的距离（逻辑像素）。
_ARROW_RIGHT_OFFSET = 14.0
#: chevron 半宽与深度。
_ARROW_HALF_WIDTH = 3.5
_ARROW_DEPTH = 3.5
#: 弹层与触发控件之间的固定间距（不压住控件）。
_POPUP_GAP = 6


def _repolish(widget: QWidget) -> None:
    """设置 objectName 后重新走一遍样式匹配，否则 QSS 不会命中。"""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class _PopupItemDelegate(QStyledItemDelegate):
    """只控制弹层选项高度的委托。

    QSS 的 ``::item`` 不支持 ``min-height``，选项高度必须由 ``sizeHint`` 决定；
    绘制仍交给 ``QStyledItemDelegate``，这样 QSS 的 hover / selected 规则继续生效。
    """

    def __init__(self, tokens: DesignTokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._height = tokens.metrics.menu_item_height

    def update_tokens(self, tokens: DesignTokens) -> None:
        self._height = tokens.metrics.menu_item_height

    def sizeHint(self, option: QStyleOptionViewItem, index: object) -> QSize:
        base = super().sizeHint(option, index)  # type: ignore[arg-type]
        return QSize(base.width(), self._height)


class SelectComboBox(QComboBox):
    """幽灵风格下拉框。

    Args:
        tokens: 当前设计令牌（决定箭头颜色）。
        parent: 父控件。
    """

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens or tokens_for("light")
        self._arrow_color = QColor(self._tokens.palette.text_muted)
        view = self.view()
        view.setObjectName(POPUP_VIEW_NAME)
        view.setStyleSheet(build_popup_stylesheet(self._tokens))
        self._item_delegate = _PopupItemDelegate(self._tokens, view)
        view.setItemDelegate(self._item_delegate)
        self._prepare_popup()
        _repolish(view)

    def set_tokens(self, tokens: DesignTokens) -> None:
        """主题切换时更新箭头颜色与弹层样式。"""
        self._tokens = tokens
        self._arrow_color = QColor(tokens.palette.text_muted)
        self.view().setStyleSheet(build_popup_stylesheet(tokens))
        self._item_delegate.update_tokens(tokens)
        self.view().doItemsLayout()
        self.update()

    def showPopup(self) -> None:
        """弹出，并把弹层与控件之间的间距固定住（不压住控件）。"""
        self._prepare_popup()
        super().showPopup()
        self._align_popup()

    def _align_popup(self) -> None:
        """让弹层与控件下底（或上顶）保持固定间距，且不压控件、不出屏。

        Qt 自己是否把弹层翻到上方并不稳定（下方不足时也可能仍向下），所以方向
        由这里按屏幕可用区决定：优先向下（顶边 = 控件底边 + 间距），下方放不下
        就翻到上方（底边 = 控件顶边 - 间距）。两种情况都不会遮住控件。
        """
        container = self.view().window()
        combo_rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()

        below_y = combo_rect.bottom() + 1 + _POPUP_GAP
        above_y = combo_rect.top() - _POPUP_GAP - container.height()
        if below_y + container.height() <= area.bottom() + 1:
            new_y = below_y
        elif above_y >= area.top():
            new_y = above_y
        else:
            new_y = below_y
        if new_y != container.y():
            container.move(container.x(), new_y)
            # 透明弹层窗口移动后需要主动重绘，否则会残留上一帧（表现为黑块）
            container.update()
            container.repaint()

    def _prepare_popup(self) -> None:
        """把弹层容器设为 SemiTransparent 无边框窗口，并重新 polish 以命中 QSS。

        Qt 的弹层是独立的 ``QComboBoxPrivateContainer`` 顶层窗口，默认带窗口边框
        与不透明背景，QSS 圆角会被裁掉；设置 ``FramelessWindowHint`` 会重建窗口，
        所以必须在 ``showPopup`` 之前完成。
        """
        container = self.view().window()
        container.setObjectName(POPUP_CONTAINER_NAME)
        if not bool(container.windowFlags() & Qt.WindowType.FramelessWindowHint):
            container.setWindowFlags(
                Qt.WindowType.Popup
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.NoDropShadowWindowHint
            )
            container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 容器自身的 QFrame 底色与边框必须由控件直接下发样式关掉，
        # 否则应用级样式表在独立顶层窗口上命不中，会把圆角切掉。
        container.setStyleSheet(
            "#ComboPopupContainer { background: transparent; border: none; }"
        )
        _repolish(container)

    def hidePopup(self) -> None:
        super().hidePopup()
        # 箭头由「朝上（展开）」恢复为「朝下」
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        expanded = self.view().isVisible()
        color = QColor(self._tokens.palette.accent) if expanded else self._arrow_color
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            center_x = self.width() - _ARROW_RIGHT_OFFSET
            center_y = self.height() / 2.0
            half_depth = _ARROW_DEPTH / 2.0
            path = QPainterPath()
            if expanded:
                # 展开：chevron 朝上
                path.moveTo(center_x - _ARROW_HALF_WIDTH, center_y + half_depth)
                path.lineTo(center_x, center_y - half_depth)
                path.lineTo(center_x + _ARROW_HALF_WIDTH, center_y + half_depth)
            else:
                path.moveTo(center_x - _ARROW_HALF_WIDTH, center_y - half_depth)
                path.lineTo(center_x, center_y + half_depth)
                path.lineTo(center_x + _ARROW_HALF_WIDTH, center_y - half_depth)
            pen = QPen(color, 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        finally:
            painter.end()
