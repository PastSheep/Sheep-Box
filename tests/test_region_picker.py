"""选区覆盖层测试（offscreen）。

真机拖拽需要真实屏幕与窗口，这里只验证构造、取消路径与坐标换算；实际选区的
像素正确性由 ``tests/test_capture.py`` 的真机用例与冒烟脚本覆盖。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gui.components.region_picker import PickResult, RegionPicker, _physical_point
from service.capture.models import CaptureRegion, NormalizedRegion


@pytest.fixture
def qapp():
    """保证存在 QApplication。"""
    app = QApplication.instance() or QApplication([])
    yield app


def test_pick_result_is_frozen() -> None:
    result = PickResult(
        hwnd=100,
        screen_rect=(10, 20, 300, 200),
        client_region=CaptureRegion(0, 0, 300, 200),
        normalized_region=NormalizedRegion(0, 0, 1, 1),
    )
    assert result.hwnd == 100
    assert result.client_region.width == 300
    assert PickResult.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_picker_uses_tool_window_flags(qapp) -> None:
    picker = RegionPicker()
    flags = picker.windowFlags()
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert picker.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_escape_emits_cancelled(qapp) -> None:
    picker = RegionPicker()
    events: list[str] = []
    picker.cancelled.connect(lambda: events.append("cancelled"))
    picker.start()
    QTest.keyClick(picker, Qt.Key.Key_Escape)
    assert events == ["cancelled"]


def test_right_click_emits_cancelled(qapp) -> None:
    picker = RegionPicker()
    events: list[str] = []
    picker.cancelled.connect(lambda: events.append("cancelled"))
    picker.start()
    QTest.mouseClick(picker, Qt.MouseButton.RightButton, pos=QPoint(40, 40))
    assert events == ["cancelled"]


def test_physical_point_matches_screen_ratio(qapp) -> None:
    screen = QGuiApplication.primaryScreen()
    geometry = screen.geometry()
    ratio = screen.devicePixelRatio()
    point = QPoint(geometry.x() + 10, geometry.y() + 20)
    x, y = _physical_point(point)
    assert x == round(10 * ratio) + round(geometry.x() * ratio)
    assert y == round(20 * ratio) + round(geometry.y() * ratio)
