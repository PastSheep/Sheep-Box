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

from gui.components import region_picker as picker_module
from gui.components.region_picker import PickResult, RegionPicker, _physical_point
from service.capture.models import (
    CaptureRegion,
    NormalizedRegion,
    WindowInfo,
)


def _window_info() -> WindowInfo:
    """构造一个可被选区组件接受的窗口快照。"""
    return WindowInfo(
        hwnd=99,
        title="Target",
        class_name="TargetClass",
        process_id=7,
        process_name="target.exe",
        client_width=800,
        client_height=600,
        screen_width=800,
        screen_height=600,
        dpi=96,
        visible=True,
        minimized=False,
        frame_rect=(0, 0, 816, 639),
        client_origin=(10, 20),
    )


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


def test_start_resets_stale_selection_state(qapp) -> None:
    """复用同一实例时，上一次的拖拽/悬停状态必须清掉。"""
    picker = RegionPicker()
    picker._origin = (1, 2)
    picker._current = (3, 4)
    picker._hover = (0, 0, 10, 10)
    picker._hover_hwnd = 42
    picker.start()
    assert picker._origin is None
    assert picker._current is None
    assert picker._hover is None
    assert picker._hover_hwnd == 0


def test_finish_window_rejects_own_handle(qapp, monkeypatch) -> None:
    """悬停句柄若回指覆盖层自身，必须取消而不是把覆盖层当成目标窗口。

    旧实现会直接拿它去查窗口信息并 ``picked``，用户拿到的就是覆盖层本身
    （关掉后句柄立刻失效）。
    """
    picker = RegionPicker()
    events: list[str] = []
    picker.picked.connect(lambda _result: events.append("picked"))
    picker.cancelled.connect(lambda: events.append("cancelled"))
    picker.start()
    picker._hover = (0, 0, 10, 10)
    picker._hover_hwnd = 99
    monkeypatch.setattr(picker, "_own_hwnd", lambda: 99)
    monkeypatch.setattr(
        picker_module,
        "get_window_info",
        lambda _hwnd: _window_info(),
    )
    picker._finish_window()
    assert events == ["cancelled"]
