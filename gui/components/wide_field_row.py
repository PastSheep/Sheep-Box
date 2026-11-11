"""偏好行组件：标签在上、控件占满整行。

渐变锚点这类需要横向铺满的控件放不进 :class:`FieldRow` 的固定 160px 控件列，
因此单独一行：标签独占一行，控件在下一行占满可用宽度。分隔线语义与
``FieldRow`` 一致（行上方可选 1px 线）。

跨语言稳健性同样由固定标签区高度保证：标签换行不会顶掉下方控件的位置。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from gui.theme.tokens import DesignTokens

__all__ = ["WideFieldRow"]


class WideFieldRow(QWidget):
    """整行偏好项：标签一行，控件在下一行铺满宽度。

    Args:
        label_text: 标签文本。
        control: 下方控件（渐变条、色带等）。
        tokens: 当前设计令牌。
        show_divider: 是否在行上方显示分隔线；首行通常为 ``False``。
        parent: 父控件。
    """

    def __init__(
        self,
        label_text: str,
        control: QWidget,
        tokens: DesignTokens,
        show_divider: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        metrics = tokens.metrics

        self._divider = QFrame(self)
        self._divider.setObjectName("Divider")
        self._divider.setFrameShape(QFrame.Shape.HLine)
        self._divider.setVisible(show_divider)

        self._label = QLabel(label_text, self)
        self._label.setObjectName("FieldLabel")
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self._control = control
        self._control.setParent(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.space_sm)
        if show_divider:
            layout.addWidget(self._divider)
        layout.addWidget(self._label)
        layout.addWidget(self._control)

    def set_label_text(self, text: str) -> None:
        """更新标签文本（语言切换后调用）。"""
        self._label.setText(text)

    def label_text(self) -> str:
        """当前标签文本。"""
        return self._label.text()

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """令牌变化时更新间距。"""
        layout = self.layout()
        if layout is not None:
            layout.setSpacing(tokens.metrics.space_sm)
