"""偏好行组件：左侧固定宽标签 + 右侧固定宽控件，顶部可选分隔线。

跨语言布局的稳健性由两处固定宽度保证：
- 标签列固定宽：不同语言文本长度不同，也不把控件列顶走；
- 控件列固定宽：不随标签长度或窗口拉伸变形。
这样切换中英文时控件位置不发生位移，是主流桌面端设置的常见处理方式。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.theme.tokens import DesignTokens

__all__ = ["FieldRow"]


class FieldRow(QWidget):
    """一行偏好设置：标签靠左、控件靠右，行上方可带 1px 分隔线。

    Args:
        label_text: 标签文本。
        control: 右侧控件（下拉框、单选框等）。
        tokens: 当前设计令牌（提供标签/控件宽度与间距）。
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
        self._label.setFixedWidth(metrics.label_width)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self._control = control
        self._control.setFixedWidth(metrics.control_width)
        self._control.setFixedHeight(metrics.control_height)
        self._control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(metrics.space_sm)
        row.addWidget(self._label)
        row.addStretch(1)
        row.addWidget(self._control, 0, Qt.AlignmentFlag.AlignVCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.space_sm)
        if show_divider:
            layout.addWidget(self._divider)
        layout.addLayout(row)

    def set_label_text(self, text: str) -> None:
        """更新标签文本（语言切换后调用）。"""
        self._label.setText(text)

    def label_text(self) -> str:
        """当前标签文本。"""
        return self._label.text()

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """令牌变化时更新宽度与间距。"""
        metrics = tokens.metrics
        self._label.setFixedWidth(metrics.label_width)
        self._control.setFixedWidth(metrics.control_width)
