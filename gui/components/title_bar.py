"""自绘标题栏：左侧程序图标与标题、中间导航条、右侧窗口按钮。

标题栏本身不处理拖动——拖动、双击最大化、贴边由 ``WM_NCHITTEST`` 返回
``HTCAPTION`` 交给系统（见 :mod:`gui.view.window_chrome`）。这里只负责：

- 画出图标、标题与底部 1px 分隔线；
- 三个 Windows 风格窗口按钮（``36×30``，关闭键悬停变红）；
- 回答"这个点能不能拖"（导航项与按钮区不能拖，避免误拖或点不中）。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from gui.theme.tokens import DesignTokens

__all__ = ["TitleBar", "WindowButton"]

#: 标题栏高度（导航条 32 高 + 上下留白，与主流桌面应用一致）。
TITLE_HEIGHT = 44
#: 窗口按钮尺寸。
_BUTTON_WIDTH = 36
_BUTTON_HEIGHT = 30
#: 关闭键悬停底色（Windows 约定）。
_CLOSE_HOVER = "#E81123"
_CLOSE_PRESSED = "#F1707A"
_ICON_SIZE = 18


class _BoxLogo(QWidget):
    """程序图标：圆角方块 + 中央缝隙，抽象表示"盒子"。"""

    def __init__(self, tokens: DesignTokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self.setFixedSize(_ICON_SIZE, _ICON_SIZE)

    def set_tokens(self, tokens: DesignTokens) -> None:
        self._tokens = tokens
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        palette = self._tokens.palette
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            body = QColor(palette.accent)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(body)
            painter.drawRoundedRect(QRectF(0.0, 0.0, 18.0, 18.0), 4.5, 4.5)
            painter.setPen(QPen(QColor(255, 255, 255, 235), 1.6))
            painter.drawLine(QPointF(4.5, 9.0), QPointF(13.5, 9.0))
            painter.setPen(QPen(QColor(255, 255, 255, 150), 1.2))
            painter.drawLine(QPointF(4.5, 12.6), QPointF(13.5, 12.6))
        finally:
            painter.end()


class WindowButton(QAbstractButton):
    """窗口控制按钮（最小化 / 最大化-还原 / 关闭）。

    Args:
        kind: ``minimize`` / ``maximize`` / ``close``。
        tokens: 设计令牌（配色随主题变化）。
    """

    def __init__(
        self,
        kind: str,
        tokens: DesignTokens,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._tokens = tokens
        self._hover = False
        self._maximized = False
        self.setFixedSize(_BUTTON_WIDTH, _BUTTON_HEIGHT)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if kind == "close":
            self.setToolTip(self.tr("Close"))
        elif kind == "minimize":
            self.setToolTip(self.tr("Minimize"))
        else:
            self.setToolTip(self.tr("Maximize"))

    def set_tokens(self, tokens: DesignTokens) -> None:
        self._tokens = tokens
        self.update()

    def set_maximized(self, maximized: bool) -> None:
        """最大化状态变化时切换图标（方框 / 双框）。"""
        if self._maximized == maximized:
            return
        self._maximized = maximized
        if self._kind == "maximize":
            self.setToolTip(self.tr("Restore"))
        self.update()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.HoverEnter:
            self._hover = True
            self.update()
        elif event.type() == QEvent.Type.HoverLeave:
            self._hover = False
            self.update()
        return super().event(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        palette = self._tokens.palette
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            pressed = self.isDown()
            if self._kind == "close" and (self._hover or pressed):
                color = QColor(_CLOSE_PRESSED if pressed else _CLOSE_HOVER)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, 4.0, 4.0)
                icon = QColor(255, 255, 255)
            elif self._hover or pressed:
                color = QColor(palette.text_primary)
                color.setAlphaF(0.06 if not pressed else 0.10)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, 4.0, 4.0)
                icon = QColor(palette.text_secondary)
            else:
                icon = QColor(palette.text_secondary)

            painter.setPen(QPen(icon, 1.0))
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            self._paint_glyph(painter, center)
        finally:
            painter.end()

    def _paint_glyph(self, painter: QPainter, center: QPointF) -> None:
        """按 Windows 的图形语言绘制按钮图标。"""
        half = 5.0
        if self._kind == "minimize":
            painter.drawLine(
                QPointF(center.x() - half, center.y()),
                QPointF(center.x() + half, center.y()),
            )
            return
        if self._kind == "close":
            inner = 4.5
            painter.drawLine(
                QPointF(center.x() - inner, center.y() - inner),
                QPointF(center.x() + inner, center.y() + inner),
            )
            painter.drawLine(
                QPointF(center.x() + inner, center.y() - inner),
                QPointF(center.x() - inner, center.y() + inner),
            )
            return
        if self._maximized:
            # 还原：两个错位的方框
            offset = 2.0
            painter.drawRect(QRectF(center.x() - 5.0, center.y() - 4.5, 7.0, 7.0))
            painter.drawRect(
                QRectF(center.x() - 3.0 + offset, center.y() - 2.5, 7.0, 7.0)
            )
            return
        painter.drawRect(QRectF(center.x() - 4.5, center.y() - 4.5, 9.0, 9.0))


class TitleBar(QWidget):
    """标题栏：``[图标] [标题] [导航条 …] [最小化] [最大化] [关闭]``。

    Args:
        tokens: 设计令牌。
        nav: 嵌在中间的导航条（由 :class:`~gui.components.nav_bar.NavBar` 提供）。
        title: 初始标题文字。
        parent: 父控件。
    """

    minimize_requested = Signal()
    maximize_toggle_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        tokens: DesignTokens,
        nav: QWidget,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._nav = nav
        self.setFixedHeight(TITLE_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        metrics = tokens.metrics
        self._logo = _BoxLogo(tokens, self)
        self._title = QLabel(title, self)
        self._title.setObjectName("WindowTitle")
        self._title_text = title
        # 标题给个上限，长语言/长名字不会把中间的导航条挤没
        self._title.setMaximumWidth(168)
        self._title.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        title_font = QFont(self._title.font())
        title_font.setPointSizeF(max(8.5, metrics.font_body - 1.5))
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title.setFont(title_font)
        self._title.setFixedHeight(TITLE_HEIGHT)
        self.set_title(title)

        self._minimize = WindowButton("minimize", tokens, self)
        self._maximize = WindowButton("maximize", tokens, self)
        self._close = WindowButton("close", tokens, self)
        self._buttons = QWidget(self)
        buttons_layout = QHBoxLayout(self._buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(0)
        for button in (self._minimize, self._maximize, self._close):
            buttons_layout.addWidget(button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(metrics.space_lg, 0, 0, 0)
        layout.setSpacing(metrics.space_sm)
        layout.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(metrics.space_xs)
        layout.addWidget(nav, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._buttons, 0, Qt.AlignmentFlag.AlignVCenter)
        self._layout = layout

        self._minimize.clicked.connect(self.minimize_requested)
        self._maximize.clicked.connect(self.maximize_toggle_requested)
        self._close.clicked.connect(self.close_requested)

    # ------------------------------------------------------------------ 状态

    def set_title(self, title: str) -> None:
        """更新标题文字（语言切换时调用），过长时右侧省略。"""
        self._title_text = title
        metrics = self._title.fontMetrics()
        self._title.setText(metrics.elidedText(title, Qt.TextElideMode.ElideRight, 160))

    def set_maximized(self, maximized: bool) -> None:
        """同步最大化状态（图标在方框/双框之间切换）。"""
        self._maximize.set_maximized(maximized)

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """切换主题令牌。"""
        self._tokens = tokens
        self._logo.set_tokens(tokens)
        for button in (self._minimize, self._maximize, self._close):
            button.set_tokens(tokens)
        self.update()

    def title_label(self) -> QLabel:
        """标题标签（测试与语言切换用）。"""
        return self._title

    def buttons(self) -> tuple[WindowButton, WindowButton, WindowButton]:
        """返回（最小化, 最大化, 关闭）三个按钮。"""
        return self._minimize, self._maximize, self._close

    # ------------------------------------------------------------------ 交互

    def is_drag_region(self, x: int, y: int) -> bool:
        """窗口坐标 ``(x, y)`` 是否能作为拖动把手。

        导航项与窗口按钮必须排除，否则会与点击、翻页抢事件。
        """
        if not (0 <= y < self.height()):
            return False
        child = self.childAt(QPoint(x, y))
        if child is None:
            return True
        if child is self._nav or self._nav.isAncestorOf(child):
            return False
        return not (child is self._buttons or self._buttons.isAncestorOf(child))

    def paintEvent(self, event: QPaintEvent) -> None:
        """只画底部 1px 分隔线，底色沿用窗口背景层。"""
        painter = QPainter(self)
        try:
            palette = self._tokens.palette
            divider = QColor(palette.divider)
            painter.fillRect(0, self.height() - 1, self.width(), 1, divider)
        finally:
            painter.end()
