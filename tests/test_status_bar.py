"""状态栏、渐变取色与锚点控件测试（offscreen，无需真实硬件）。

覆盖三层：
- :class:`UsageGradient`：端点、插值、5% 粒度缓存与越界钳制；
- :class:`StatusBar`：快照刷新、GPU 数量动态增减、无 GPU 时隐藏；
- :class:`GradientStopsControl`：新增 / 改色 / 删除与「至少 2 个锚点」下限；
- :class:`StatusBarConfig`：锚点数量、位置唯一性与颜色格式校验。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pydantic import ValidationError
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel

from config.schema import GradientStop, StatusBarConfig
from gui.components.gradient_stops import GradientStopsControl
from gui.components.status_bar import StatusBar
from gui.components.usage_gradient import UsageGradient
from gui.theme.tokens import tokens_for
from service.sysinfo.models import CpuSample, GpuSample, MemorySample, SystemSnapshot


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _snapshot(
    cpu: float = 12.0,
    memory: float = 42.0,
    gpus: tuple[GpuSample, ...] = (),
) -> SystemSnapshot:
    return SystemSnapshot(
        timestamp=1.0,
        cpu=CpuSample(percent=cpu, logical_cores=12),
        memory=MemorySample(
            total=16 * 1024**3, used=7 * 1024**3, available=9 * 1024**3, percent=memory
        ),
        gpus=gpus,
    )


# ---------------------------------------------------------------- UsageGradient


def test_gradient_endpoints_and_midpoint() -> None:
    gradient = UsageGradient([(0.0, "#17A05E"), (100.0, "#D94A4A")])
    assert gradient.color_at(0.0).name().lower() == "#17a05e"
    assert gradient.color_at(100.0).name().lower() == "#d94a4a"
    midpoint = gradient.color_at(50.0)
    assert 0x17 < midpoint.red() < 0xD9
    assert 0xA0 > midpoint.green() > 0x4A


def test_gradient_clamps_out_of_range() -> None:
    gradient = UsageGradient([(0.0, "#17A05E"), (100.0, "#D94A4A")])
    assert gradient.color_at(-5.0).name().lower() == "#17a05e"
    assert gradient.color_at(150.0).name().lower() == "#d94a4a"


def test_gradient_caches_at_five_percent_buckets() -> None:
    gradient = UsageGradient([(0.0, "#17A05E"), (100.0, "#D94A4A")])
    # 51% 与 52% 四舍五入到同一 5% 档（50），只应产生一个缓存项
    gradient.color_at(51.0)
    gradient.color_at(52.0)
    assert gradient.cached_levels() == 1
    gradient.color_at(53.0)  # 归到 55 档
    assert gradient.cached_levels() == 2
    gradient.color_at(58.0)  # 归到 60 档
    assert gradient.cached_levels() == 3


def test_gradient_cache_is_shared_for_equal_lookup() -> None:
    gradient = UsageGradient([(0.0, "#17A05E"), (100.0, "#D94A4A")])
    first = gradient.color_at(37.0)
    second = gradient.color_at(35.0)
    assert first == second


def test_gradient_multi_anchor_picks_segment() -> None:
    gradient = UsageGradient(
        [(0.0, "#17A05E"), (50.0, "#E0A008"), (80.0, "#D94A4A"), (100.0, "#D94A4A")]
    )
    assert gradient.color_at(50.0).name().lower() == "#e0a008"
    assert gradient.color_at(80.0).name().lower() == "#d94a4a"
    assert gradient.color_at(100.0).name().lower() == "#d94a4a"


def test_gradient_requires_at_least_one_stop() -> None:
    with pytest.raises(ValueError):
        UsageGradient([])


# ---------------------------------------------------------------- StatusBar


def test_status_bar_shows_cpu_and_memory(qapp) -> None:
    bar = StatusBar(tokens=tokens_for("light"))
    bar.apply_snapshot(_snapshot(cpu=12.0, memory=42.0))
    values = [label.text() for label in bar.findChildren(QLabel, "StatusValue")]
    assert "12%" in values
    assert "42%" in values
    bar.deleteLater()


def test_status_bar_hides_gpu_without_adapter(qapp) -> None:
    bar = StatusBar(tokens=tokens_for("light"))
    bar.apply_snapshot(_snapshot())
    assert not bar._gpu_host.isVisible() or bar._gpu_items == []
    bar.deleteLater()


def test_status_bar_adds_and_removes_gpu_items(qapp) -> None:
    bar = StatusBar(tokens=tokens_for("light"))
    bar.apply_snapshot(
        _snapshot(gpus=(GpuSample(0, "RTX", 30.0),)),
    )
    assert len(bar._gpu_items) == 1

    bar.apply_snapshot(
        _snapshot(gpus=(GpuSample(0, "RTX", 30.0), GpuSample(1, "RTX", 55.0))),
    )
    assert len(bar._gpu_items) == 2

    bar.apply_snapshot(_snapshot())
    assert bar._gpu_items == []
    bar.deleteLater()


def test_status_bar_single_gpu_label_has_no_index(qapp) -> None:
    bar = StatusBar(tokens=tokens_for("light"))
    bar.apply_snapshot(_snapshot(gpus=(GpuSample(0, "RTX", 30.0),)))
    label = bar._gpu_items[0].findChild(QLabel, "StatusLabel")
    assert label is not None
    assert "1" not in label.text()
    bar.deleteLater()


# ---------------------------------------------------------------- 锚点控件


def test_stops_control_starts_with_configured_stops(qapp) -> None:
    control = GradientStopsControl(stops=[(0.0, "#17A05E"), (100.0, "#D94A4A")])
    assert control.stops() == [(0.0, "#17A05E"), (100.0, "#D94A4A")]
    control.deleteLater()


def test_stops_control_adds_stop_with_sampled_color(qapp) -> None:
    control = GradientStopsControl(stops=[(0.0, "#17A05E"), (100.0, "#D94A4A")])
    emitted: list[list[tuple[float, str]]] = []
    control.stops_changed.connect(emitted.append)

    control._add_stop(30.0)

    stops = control.stops()
    assert len(stops) == 3
    assert stops[1][0] == 30.0
    assert stops[1][1].startswith("#")
    assert emitted and len(emitted[-1]) == 3
    control.deleteLater()


def test_stops_control_ignores_too_close_positions(qapp) -> None:
    control = GradientStopsControl(stops=[(0.0, "#17A05E"), (100.0, "#D94A4A")])
    control._add_stop(0.2)
    assert len(control.stops()) == 2
    control.deleteLater()


def test_stops_control_keeps_minimum_two_stops(qapp) -> None:
    control = GradientStopsControl(stops=[(0.0, "#17A05E"), (100.0, "#D94A4A")])
    control._delete_stop(0)
    assert len(control.stops()) == 2
    control.deleteLater()


def test_stops_control_deletes_and_recolors(qapp) -> None:
    control = GradientStopsControl(
        stops=[(0.0, "#17A05E"), (50.0, "#E0A008"), (100.0, "#D94A4A")]
    )
    control._delete_stop(1)
    assert [at for at, _c in control.stops()] == [0.0, 100.0]

    control._update_stop_color(0, "#2F6FEB")
    assert control.stops()[0] == (0.0, "#2F6FEB")
    control.deleteLater()


def test_stops_control_supplies_missing_endpoints(qapp) -> None:
    """配置里只有中间锚点时，两端自动补齐，保证渐变覆盖 0~100。"""
    control = GradientStopsControl(stops=[(40.0, "#E0A008"), (70.0, "#D94A4A")])
    positions = [at for at, _c in control.stops()]
    assert positions[0] == 0.0
    assert positions[-1] == 100.0
    assert len(positions) == 4
    control.deleteLater()


def test_stops_control_endpoints_are_fixed(qapp) -> None:
    """0% 与 100% 端点不能拖动、不能删除，但仍可改颜色。"""
    control = GradientStopsControl(
        stops=[(0.0, "#17A05E"), (40.0, "#E0A008"), (100.0, "#D94A4A")]
    )
    assert control._is_endpoint(0)
    assert control._is_endpoint(2)
    assert not control._is_endpoint(1)

    control._delete_stop(0)
    control._delete_stop(2)
    assert [at for at, _c in control.stops()] == [0.0, 40.0, 100.0]

    control._update_stop_color(0, "#2F6FEB")
    assert control.stops()[0] == (0.0, "#2F6FEB")
    control.deleteLater()


def test_stops_control_drag_moves_middle_stop(qapp) -> None:
    """左键按住中间节点拖动会改变位置，且一次拖动只广播一次。"""
    control = GradientStopsControl(
        stops=[(0.0, "#17A05E"), (50.0, "#E0A008"), (100.0, "#D94A4A")]
    )
    control.resize(300, 62)
    emitted: list[list[tuple[float, str]]] = []
    control.stops_changed.connect(emitted.append)

    start = QPointF(control._x_for(50.0), control.height() / 2)
    control.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, start))
    control.mouseMoveEvent(
        _mouse_event(QEvent.Type.MouseMove, QPointF(start.x() + 40, start.y()))
    )
    control.mouseMoveEvent(
        _mouse_event(QEvent.Type.MouseMove, QPointF(start.x() + 80, start.y()))
    )
    control.mouseReleaseEvent(
        _mouse_event(QEvent.Type.MouseButtonRelease, QPointF(start.x() + 80, start.y()))
    )

    moved = control.stops()[1][0]
    assert moved > 50.0
    assert len(emitted) == 1
    control.deleteLater()


def test_stops_control_cannot_drag_endpoint(qapp) -> None:
    """按住端点拖动不会有任何位置变化。"""
    control = GradientStopsControl(stops=[(0.0, "#17A05E"), (100.0, "#D94A4A")])
    control.resize(300, 62)
    start = QPointF(control._x_for(0.0), control.height() / 2)
    control.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, start))
    control.mouseMoveEvent(
        _mouse_event(QEvent.Type.MouseMove, QPointF(start.x() + 60, start.y()))
    )
    control.mouseReleaseEvent(
        _mouse_event(QEvent.Type.MouseButtonRelease, QPointF(start.x() + 60, start.y()))
    )
    assert control.stops()[0][0] == 0.0
    control.deleteLater()


def test_stops_control_labels_alternate_when_crowded(qapp) -> None:
    """标签默认在上方，两个锚点挨得近时第二个改到下方。"""
    control = GradientStopsControl(
        stops=[(0.0, "#17A05E"), (5.0, "#E0A008"), (100.0, "#D94A4A")]
    )
    control.resize(300, 62)
    sides = control._label_sides(QFontMetrics(QFont()))
    assert sides[0] == 0
    assert sides[1] == 1
    assert sides[2] == 0
    control.deleteLater()


def _mouse_event(event_type, pos):
    """构造一个鼠标事件，供直接调用控件的鼠标处理器（用 7 参重载避免弃用）。"""
    return QMouseEvent(
        event_type,
        pos,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


# ---------------------------------------------------------------- 配置校验


def test_status_bar_config_defaults() -> None:
    config = StatusBarConfig()
    assert config.refresh_interval_ms == 1000
    assert len(config.gradient_stops) == 4


def test_status_bar_config_rejects_single_stop() -> None:
    with pytest.raises(ValidationError):
        StatusBarConfig(gradient_stops=[GradientStop(at=50.0, color="#17A05E")])


def test_status_bar_config_rejects_duplicate_positions() -> None:
    with pytest.raises(ValidationError):
        StatusBarConfig(
            gradient_stops=[
                GradientStop(at=0.0, color="#17A05E"),
                GradientStop(at=0.0, color="#D94A4A"),
            ]
        )


def test_status_bar_config_rejects_bad_color() -> None:
    with pytest.raises(ValidationError):
        StatusBarConfig(
            gradient_stops=[
                GradientStop(at=0.0, color="green"),
                GradientStop(at=100.0, color="#D94A4A"),
            ]
        )


def test_status_bar_config_rejects_out_of_range_interval() -> None:
    with pytest.raises(ValidationError):
        StatusBarConfig(refresh_interval_ms=100)
