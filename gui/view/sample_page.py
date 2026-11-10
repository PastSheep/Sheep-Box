"""示例页：用于验证导航条的胶囊展开与收起，不承载任何真实业务。

示例页只放一张玻璃卡片与一段说明文字，存在的意义是提供第二个页面，让导航条
的「选中项展开成胶囊、其余项收缩成图标」有可切换的对象；等真正需要多页时，
把这个页面替换成业务页即可，主窗口结构不用再改。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.components.glass_card import GlassCard
from gui.theme.tokens import DesignTokens, tokens_for

__all__ = ["SamplePage"]


class SamplePage(QWidget):
    """示例页（导航条交互验证用）。

    Args:
        parent: 父控件。
        tokens: 初始设计令牌。
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        tokens: DesignTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: DesignTokens = tokens or tokens_for("light")
        metrics = self._tokens.metrics

        self._title = QLabel(self)
        self._title.setObjectName("PageTitle")
        self._subtitle = QLabel(self)
        self._subtitle.setObjectName("PageSubtitle")

        self._card = GlassCard(tokens=self._tokens, parent=self)
        self._section = QLabel(self._card)
        self._section.setObjectName("SectionLabel")
        self._body = QLabel(self._card)
        self._body.setObjectName("BodyText")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(
            metrics.space_lg,
            metrics.space_lg,
            metrics.space_lg,
            metrics.space_lg,
        )
        card_layout.setSpacing(metrics.space_sm)
        card_layout.addWidget(self._section)
        card_layout.addWidget(self._body)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(
            metrics.space_xl,
            metrics.space_md,
            metrics.space_xl,
            metrics.space_xl,
        )
        page_layout.setSpacing(0)
        page_layout.addWidget(self._title)
        page_layout.addSpacing(metrics.space_xs)
        page_layout.addWidget(self._subtitle)
        page_layout.addSpacing(metrics.space_lg)
        page_layout.addWidget(self._card, 0)
        page_layout.addStretch(1)

        self.retranslate_ui()

    def apply_tokens(self, tokens: DesignTokens) -> None:
        """主题切换时更新令牌（卡片会重建模糊背景）。"""
        self._tokens = tokens
        self._card.set_tokens(tokens)

    def retranslate_ui(self) -> None:
        """重设界面文本（语言切换后由主窗口调用）。"""
        self._title.setText(self.tr("Sample"))
        self._subtitle.setText(self.tr("A demo page for the tab navigation"))
        self._section.setText(self.tr("Navigation"))
        self._body.setText(
            self.tr(
                "The active page expands into a pill; inactive pages stay as "
                "icons and show their title on hover. When there are too many "
                "pages, page-turn arrows appear on both sides."
            )
        )
