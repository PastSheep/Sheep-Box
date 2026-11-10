"""导航条组件测试（offscreen）。

覆盖：
- 追加导航项与初始选中页；
- 选中项展开为胶囊、其余项收缩为圆形（目标宽度）；
- 宽度不足时进入翻页模式；
- 语言切换后按新文字重算胶囊宽度；
- 主题切换后仍能正常计算几何。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gui.components.nav_bar import NavBar
from gui.theme.tokens import DARK, LIGHT


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_nav(items: list[tuple[str, str]]) -> NavBar:
    nav = NavBar(LIGHT)
    for icon, title in items:
        nav.add_item(icon, title)
    return nav


def test_add_item_and_default_selection(qapp):
    """两项导航，默认选中第一项。"""
    nav = _make_nav([("settings", "Settings"), ("sample", "Sample")])
    assert nav.count() == 2
    assert nav.current() == 0
    nav.close()


def test_selected_item_expands_others_collapse(qapp):
    """选中项宽于圆形位，其余项等于圆形位。"""
    nav = _make_nav([("settings", "Settings"), ("sample", "Sample")])
    circle = float(LIGHT.metrics.nav_height)
    widths = nav.target_widths()
    assert widths[0] > circle
    assert widths[1] == pytest.approx(circle)

    nav.set_current(1, animate=False)
    widths = nav.target_widths()
    assert widths[1] > circle
    assert widths[0] == pytest.approx(circle)
    nav.close()


def test_set_current_emits_signal(qapp):
    """切换当前页发出 currentChanged。"""
    nav = _make_nav([("settings", "Settings"), ("sample", "Sample")])
    received: list[int] = []
    nav.currentChanged.connect(received.append)
    nav.set_current(1, animate=False)
    assert received == [1]
    nav.close()


def test_paging_when_width_is_narrow(qapp):
    """项总宽超出控件宽度时进入翻页模式，放宽后退出。"""
    nav = _make_nav([("sample", f"Page {index}") for index in range(6)])
    nav.resize(200, 40)
    assert nav.needs_paging() is True
    assert nav.sizeHint().width() > 200
    nav.resize(900, 40)
    assert nav.needs_paging() is False
    nav.close()


def test_page_target_advances_and_clamps(qapp):
    """翻页步长：向右为正，不溢出时不移动，且不超过内容总宽。"""
    nav = _make_nav([("sample", f"Page {index}") for index in range(10)])
    nav.resize(330, 44)
    assert nav.needs_paging() is True
    forward = nav.page_target(1)
    assert forward > 0
    assert forward <= 330  # 一次最多一屏
    assert nav.page_target(-1) == pytest.approx(0.0)
    nav.resize(1200, 44)
    assert nav.page_target(1) == pytest.approx(0.0)
    nav.close()


def test_page_target_covers_three_items_when_room_allows(qapp):
    """空间足够时，一次翻页至少跨过 3 个项。"""
    nav = _make_nav([("sample", f"Page {index}") for index in range(12)])
    nav.resize(300, 44)  # 12 个圆形项共 428px，一屏放不下，但一屏能容下 3 项以上
    targets = nav.target_widths()
    gap = float(LIGHT.metrics.nav_gap)
    three_items = sum(targets[:3]) + gap * 3
    assert nav.needs_paging() is True
    assert nav.page_target(1) == pytest.approx(three_items)
    nav.close()


def test_set_titles_recalculates_width(qapp):
    """语言切换后胶囊宽度按新标题重算。"""
    nav = _make_nav([("settings", "Settings"), ("sample", "Sample")])
    before = nav.target_widths()[0]
    nav.set_titles(["设置", "示例"])
    after = nav.target_widths()[0]
    assert after != pytest.approx(before)
    nav.close()


def test_apply_tokens_keeps_geometry(qapp):
    """切到深色令牌后仍能算出同样的几何（两套 Metrics 一致）。"""
    nav = _make_nav([("settings", "Settings"), ("sample", "Sample")])
    nav.apply_tokens(DARK)
    assert nav.target_widths()[0] > float(DARK.metrics.nav_height)
    assert nav.sizeHint().height() == DARK.metrics.nav_height + (
        DARK.metrics.nav_padding * 2
    )
    nav.close()
