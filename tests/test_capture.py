"""窗口区域截图模块测试。

纯逻辑部分（区域换算、判黑、裁剪）无需桌面；门面编排用假后端验证降级与异常；
真机用例默认跳过，设置 ``SHEEPBOX_REAL_DESKTOP=1`` 后才会真正抓取窗口。
"""

import os
import sys
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from common.exceptions import (
    CaptureBackendError,
    CaptureOccludedError,
    CaptureRegionError,
    CaptureUnavailableError,
    WindowNotVisibleError,
    WindowOutOfScreenError,
)
from service.capture import capturer as capturer_module
from service.capture import windows as windows_module
from service.capture.backends import dxgi as dxgi_module
from service.capture.backends import gdi as gdi_module
from service.capture.backends import wgc as wgc_module
from service.capture.backends._dxgi_native import AccessLostError
from service.capture.backends.gdi import crop_rows
from service.capture.capturer import WindowCapturer
from service.capture.models import (
    SPACE_CLIENT,
    SPACE_SCREEN,
    CaptureOptions,
    CaptureRegion,
    NormalizedRegion,
    ScreenFrame,
    WindowInfo,
    blank_ratio,
)
from service.capture.windows import client_to_screen_rect, region_from_screen

_WHITE = bytes([255, 255, 255, 255])
_BLACK = bytes([0, 0, 0, 255])


def _window(**overrides: object) -> WindowInfo:
    """构造一个尺寸规整的窗口信息，便于各用例覆盖字段。"""
    values: dict[str, object] = {
        "hwnd": 1234,
        "title": "Demo",
        "class_name": "DemoClass",
        "process_id": 42,
        "process_name": "demo.exe",
        "client_width": 800,
        "client_height": 600,
        "screen_width": 800,
        "screen_height": 600,
        "dpi": 96,
        "visible": True,
        "minimized": False,
        "frame_rect": (0, 0, 816, 639),
        "client_origin": (10, 20),
    }
    values.update(overrides)
    return WindowInfo(**values)  # type: ignore[arg-type]


def _frame(
    window: WindowInfo,
    *,
    width: int = 10,
    height: int = 10,
    data: bytes | None = None,
    backend: str = "gdi-window",
    space: str = SPACE_CLIENT,
) -> ScreenFrame:
    """构造一帧测试像素。"""
    payload = data if data is not None else _WHITE * (width * height)
    return ScreenFrame(
        width=width,
        height=height,
        data=payload,
        region=CaptureRegion(0, 0, width, height),
        space=space,
        backend=backend,
        window=window,
        timestamp=0.0,
    )


# --------------------------------------------------------------------- 区域


def test_clamp_shifts_negative_origin() -> None:
    region = CaptureRegion(-10, -5, 100, 50).clamp(200, 100)
    assert region == CaptureRegion(0, 0, 90, 45)


def test_clamp_trims_bottom_right() -> None:
    region = CaptureRegion(150, 90, 100, 50).clamp(200, 100)
    assert region == CaptureRegion(150, 90, 50, 10)


def test_clamp_returns_empty_when_fully_outside() -> None:
    region = CaptureRegion(300, 200, 10, 10).clamp(200, 100)
    assert region.empty
    assert region.width == 0 and region.height == 0


def test_full_client_region() -> None:
    assert CaptureRegion.full(800, 600) == CaptureRegion(0, 0, 800, 600)


def test_normalized_to_pixels_basic() -> None:
    region = NormalizedRegion(0.5, 0.25, 0.25, 0.5).to_pixels(800, 600)
    assert region == CaptureRegion(400, 150, 200, 300)


def test_normalized_to_pixels_clamps_ratios() -> None:
    region = NormalizedRegion(-0.5, 1.5, 2.0, 0.1).to_pixels(100, 100)
    assert region.x == 0 and region.y >= 0
    assert region.width >= 1 and region.height >= 1


def test_normalized_to_pixels_keeps_one_pixel_minimum() -> None:
    region = NormalizedRegion(0.999, 0.999, 0.0001, 0.0001).to_pixels(100, 100)
    assert region.width >= 1 and region.height >= 1
    assert region.x + region.width <= 100
    assert region.y + region.height <= 100


def test_normalized_to_pixels_rejects_invalid_size() -> None:
    with pytest.raises(ValueError):
        NormalizedRegion(0, 0, 1, 1).to_pixels(0, 100)


# --------------------------------------------------------------------- 模型


def test_capture_options_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError):
        CaptureOptions(backend="magic")


def test_capture_options_rejects_unknown_space() -> None:
    with pytest.raises(ValueError):
        CaptureOptions(space="world")


def test_screen_frame_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError):
        ScreenFrame(
            width=2,
            height=2,
            data=b"\x00" * 8,
            region=CaptureRegion(0, 0, 2, 2),
            space=SPACE_CLIENT,
            backend="gdi-window",
            window=_window(),
            timestamp=0.0,
        )


def test_screen_frame_stride() -> None:
    frame = _frame(_window(), width=4, height=3)
    assert frame.stride == 16


def test_window_capturable_and_aspect() -> None:
    window = _window()
    assert window.capturable
    assert window.aspect_ratio == pytest.approx(800 / 600)
    assert not _window(minimized=True).capturable
    assert _window(screen_width=0, screen_height=0).aspect_ratio == 0.0


# --------------------------------------------------------------------- 判黑


def test_blank_ratio_black_frame() -> None:
    assert blank_ratio(_BLACK * 100) == pytest.approx(1.0)


def test_blank_ratio_white_frame_is_not_blank() -> None:
    assert blank_ratio(_WHITE * 100) == pytest.approx(0.0)


def test_blank_ratio_colorful_frame_is_not_blank() -> None:
    pixels = bytes([20, 120, 220, 255]) * 50 + bytes([220, 20, 20, 255]) * 50
    assert blank_ratio(pixels) < 0.95


# --------------------------------------------------------------------- 裁剪


def test_crop_rows_extracts_sub_region() -> None:
    # 4x3 图，每像素颜色按 x 编码，裁出 (1,1) 起 2x2
    rows = []
    for _y in range(3):
        for x in range(4):
            rows.append(bytes([x, x, x, 255]))
    data = b"".join(rows)
    cropped = crop_rows(data, 4, CaptureRegion(1, 1, 2, 2))
    assert len(cropped) == 2 * 2 * 4
    assert cropped[0:4] == bytes([1, 1, 1, 255])
    assert cropped[4:8] == bytes([2, 2, 2, 255])


def test_crop_rows_rejects_empty_region() -> None:
    with pytest.raises(CaptureRegionError):
        crop_rows(b"\x00" * 16, 2, CaptureRegion(0, 0, 0, 2))


# --------------------------------------------------------------------- 坐标


def test_client_to_screen_rect_scales_unaware_window() -> None:
    window = _window(
        client_width=1280,
        client_height=720,
        screen_width=1600,
        screen_height=900,
        client_origin=(100, 50),
    )
    left, top, width, height = client_to_screen_rect(
        window, CaptureRegion(640, 360, 320, 180)
    )
    assert (left, top) == (100 + 800, 50 + 450)
    assert (width, height) == (400, 225)


def _patch_hit_candidates(
    monkeypatch: pytest.MonkeyPatch,
    rects: dict[int, tuple[int, int, int, int]],
    hidden: set[int] | None = None,
) -> None:
    """把候选校验绕到可控的矩形与可见性表上。"""
    hidden = hidden or set()
    monkeypatch.setattr(
        windows_module._win32, "is_visible", lambda hwnd: hwnd not in hidden
    )
    monkeypatch.setattr(
        windows_module._win32,
        "window_frame_rect",
        lambda hwnd: rects.get(hwnd, (0, 0, 0, 0)),
    )


def test_hwnd_from_point_skips_excluded_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """选区覆盖层必须被跳过，否则选中的永远是覆盖层自己。"""
    monkeypatch.setattr(windows_module._win32, "window_from_point", lambda _x, _y: 111)
    monkeypatch.setattr(windows_module._win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(windows_module._win32, "window_below", lambda _hwnd: 222)
    _patch_hit_candidates(monkeypatch, {111: (0, 0, 100, 100), 222: (0, 0, 100, 100)})
    assert windows_module.hwnd_from_point(10, 10) == 111
    assert windows_module.hwnd_from_point(10, 10, exclude=111) == 222


def test_hwnd_from_point_skips_invisible_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """z 序上层是隐藏系统窗口（MSCTFIME UI 等）时要继续下探。"""
    monkeypatch.setattr(windows_module._win32, "window_from_point", lambda _x, _y: 111)
    monkeypatch.setattr(windows_module._win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(windows_module._win32, "window_below", lambda _hwnd: 222)
    _patch_hit_candidates(
        monkeypatch,
        {111: (0, 0, 100, 100), 222: (0, 0, 100, 100)},
        hidden={111},
    )
    assert windows_module.hwnd_from_point(10, 10) == 222
    assert windows_module.hwnd_from_point(10, 10, exclude=111) == 222


def test_hwnd_from_point_skips_candidate_not_covering_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """可见但不包含光标点的候选不能返回（topmost 双窗口会选错窗）。"""
    monkeypatch.setattr(windows_module._win32, "window_from_point", lambda _x, _y: 111)
    monkeypatch.setattr(windows_module._win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(windows_module._win32, "window_below", lambda _hwnd: 222)
    _patch_hit_candidates(monkeypatch, {111: (0, 0, 5, 5), 222: (0, 0, 100, 100)})
    assert windows_module.hwnd_from_point(10, 10) == 222


def test_hwnd_from_point_returns_zero_when_nothing_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整条链都没有可用候选时给 0，让调用方取消而不是选错窗。"""
    monkeypatch.setattr(windows_module._win32, "window_from_point", lambda _x, _y: 111)
    monkeypatch.setattr(windows_module._win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(windows_module._win32, "window_below", lambda _hwnd: 0)
    _patch_hit_candidates(monkeypatch, {}, hidden={111})
    assert windows_module.hwnd_from_point(10, 10) == 0


def test_hwnd_from_point_guards_against_below_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``GW_HWNDNEXT`` 异常回指自身时不能死循环。"""
    monkeypatch.setattr(windows_module._win32, "window_from_point", lambda _x, _y: 111)
    monkeypatch.setattr(windows_module._win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(windows_module._win32, "window_below", lambda _hwnd: 111)
    _patch_hit_candidates(monkeypatch, {111: (0, 0, 100, 100)})
    assert windows_module.hwnd_from_point(10, 10, exclude=111) == 0


def test_region_from_screen_inverts_scaling_and_clamps() -> None:
    window = _window(
        client_width=1280,
        client_height=720,
        screen_width=1600,
        screen_height=900,
        client_origin=(100, 50),
    )
    region = region_from_screen(window, (100 + 800, 50 + 450, 400, 225))
    assert region == CaptureRegion(640, 360, 320, 180)

    outside = region_from_screen(window, (100 + 1600, 50, 400, 100))
    assert outside.empty


# --------------------------------------------------------------------- 门面


def _patch_window(monkeypatch: pytest.MonkeyPatch, window: WindowInfo) -> None:
    """让门面看到指定窗口，并让「窗口是否在屏幕上」恒为真。"""
    monkeypatch.setattr(
        capturer_module.windows, "get_window_info", lambda _hwnd: window
    )
    monkeypatch.setattr(
        capturer_module._win32, "virtual_screen_rect", lambda: (0, 0, 1920, 1080)
    )


def test_capturer_rejects_unimplemented_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_window(monkeypatch, _window())
    capturer = WindowCapturer(CaptureOptions(backend="wgc"))
    with pytest.raises(CaptureUnavailableError):
        capturer.capture(1234, CaptureRegion(0, 0, 10, 10))
    capturer.close()


def test_capturer_rejects_invisible_window(monkeypatch: pytest.MonkeyPatch) -> None:
    window = _window(visible=False)
    _patch_window(monkeypatch, window)
    with pytest.raises(WindowNotVisibleError):
        WindowCapturer().capture(1234, CaptureRegion(0, 0, 10, 10))


def test_capturer_rejects_out_of_bounds_without_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_window(monkeypatch, _window())
    with pytest.raises(CaptureRegionError):
        WindowCapturer(CaptureOptions(clamp_region=False)).capture(
            1234, CaptureRegion(900, 0, 10, 10)
        )


def test_capturer_rejects_fully_outside_region(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_window(monkeypatch, _window())
    with pytest.raises(CaptureRegionError):
        WindowCapturer().capture(1234, CaptureRegion(900, 700, 10, 10))


def test_capturer_returns_window_frame_when_not_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _window()
    _patch_window(monkeypatch, window)
    monkeypatch.setattr(
        capturer_module.GdiWindowBackend,
        "capture",
        lambda self, region, space: _frame(
            window, width=region.width, height=region.height
        ),
    )
    frame = WindowCapturer().capture(1234, CaptureRegion(0, 0, 10, 10))
    assert frame.backend == "gdi-window"
    assert frame.degraded is False


def _dxgi_unavailable(*_args: object, **_kwargs: object) -> ScreenFrame:
    """模拟当前环境没有可用的桌面复制。"""
    raise CaptureUnavailableError("模拟桌面复制不可用")


def test_capturer_degrades_to_screen_when_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _window()
    _patch_window(monkeypatch, window)
    monkeypatch.setattr(capturer_module.windows, "is_occluded", lambda *a, **k: False)
    monkeypatch.setattr(
        capturer_module.GdiWindowBackend,
        "capture",
        lambda self, region, space: _frame(
            window,
            width=region.width,
            height=region.height,
            data=_BLACK * (region.width * region.height),
        ),
    )
    monkeypatch.setattr(
        capturer_module.GdiWindowBackend,
        "capture_print_window",
        lambda self, region: _frame(
            window,
            width=region.width,
            height=region.height,
            data=_BLACK * (region.width * region.height),
        ),
    )
    monkeypatch.setattr(
        capturer_module.DxgiDesktopBackend, "capture", _dxgi_unavailable
    )
    monkeypatch.setattr(
        capturer_module.GdiScreenBackend,
        "capture",
        lambda self, region, space: _frame(
            window,
            width=region.width,
            height=region.height,
            backend="screen",
            space="screen",
        ),
    )
    frame = WindowCapturer().capture(1234, CaptureRegion(0, 0, 10, 10))
    assert frame.backend == "screen"
    assert frame.degraded is True


def test_capturer_prefers_dxgi_when_window_surface_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _window()
    _patch_window(monkeypatch, window)
    monkeypatch.setattr(capturer_module.windows, "is_occluded", lambda *a, **k: False)
    monkeypatch.setattr(
        capturer_module.GdiWindowBackend,
        "capture",
        lambda self, region, space: _frame(
            window,
            width=region.width,
            height=region.height,
            data=_BLACK * (region.width * region.height),
        ),
    )
    monkeypatch.setattr(
        capturer_module.GdiWindowBackend,
        "capture_print_window",
        lambda self, region: _frame(
            window,
            width=region.width,
            height=region.height,
            data=_BLACK * (region.width * region.height),
        ),
    )
    monkeypatch.setattr(
        capturer_module.DxgiDesktopBackend,
        "capture",
        lambda self, region, space: _frame(
            window,
            width=region.width,
            height=region.height,
            backend="dxgi",
            space="screen",
        ),
    )
    frame = WindowCapturer().capture(1234, CaptureRegion(0, 0, 10, 10))
    assert frame.backend == "dxgi"
    assert frame.degraded is True
    assert frame.space == SPACE_SCREEN


def test_capturer_keeps_blank_frame_when_detect_blank_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _window()
    _patch_window(monkeypatch, window)
    monkeypatch.setattr(
        capturer_module.GdiWindowBackend,
        "capture",
        lambda self, region, space: _frame(
            window,
            width=region.width,
            height=region.height,
            data=_BLACK * (region.width * region.height),
        ),
    )
    frame = WindowCapturer(CaptureOptions(detect_blank=False)).capture(
        1234, CaptureRegion(0, 0, 10, 10)
    )
    assert frame.backend == "gdi-window"
    assert frame.degraded is False
    assert blank_ratio(frame.data) == pytest.approx(1.0)


def test_capturer_falls_back_when_window_bitblt_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _window()
    _patch_window(monkeypatch, window)
    monkeypatch.setattr(capturer_module.windows, "is_occluded", lambda *a, **k: False)

    def _boom(self: object, region: CaptureRegion, space: str) -> ScreenFrame:
        raise CaptureBackendError("BitBlt 失败")

    monkeypatch.setattr(capturer_module.GdiWindowBackend, "capture", _boom)
    monkeypatch.setattr(
        capturer_module.DxgiDesktopBackend, "capture", _dxgi_unavailable
    )
    monkeypatch.setattr(
        capturer_module.GdiScreenBackend,
        "capture",
        lambda self, region, space: _frame(
            window,
            width=region.width,
            height=region.height,
            backend="screen",
            space="screen",
        ),
    )
    frame = WindowCapturer().capture(1234, CaptureRegion(0, 0, 10, 10))
    assert frame.backend == "screen"


def test_capturer_raises_when_occluded(monkeypatch: pytest.MonkeyPatch) -> None:
    window = _window()
    _patch_window(monkeypatch, window)
    monkeypatch.setattr(capturer_module.windows, "is_occluded", lambda *a, **k: True)
    with pytest.raises(CaptureOccludedError):
        WindowCapturer(CaptureOptions(backend="screen")).capture(
            1234, CaptureRegion(0, 0, 10, 10)
        )


def test_capturer_accepts_normalized_region(monkeypatch: pytest.MonkeyPatch) -> None:
    window = _window()
    _patch_window(monkeypatch, window)
    captured: list[CaptureRegion] = []

    def _capture(self: object, region: CaptureRegion, space: str) -> ScreenFrame:
        captured.append(region)
        return _frame(window, width=region.width, height=region.height)

    monkeypatch.setattr(capturer_module.GdiWindowBackend, "capture", _capture)
    WindowCapturer().capture(1234, NormalizedRegion(0.5, 0.5, 0.25, 0.25))
    assert captured[0] == CaptureRegion(400, 300, 200, 150)


def test_capturer_marks_occluded_when_verification_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """关掉遮挡校验时，帧必须标记 ``occluded=True``。

    修复前该字段全仓从不置位，消费者无法区分「确认没被遮挡」和「压根没检查」。
    """
    window = _window()
    _patch_window(monkeypatch, window)
    monkeypatch.setattr(
        capturer_module.GdiScreenBackend,
        "capture",
        lambda self, region, space: _frame(
            window,
            width=region.width,
            height=region.height,
            backend="screen",
            space="screen",
        ),
    )
    unchecked = WindowCapturer(
        CaptureOptions(backend="screen", verify_occlusion=False)
    ).capture(1234, CaptureRegion(0, 0, 10, 10))
    assert unchecked.occluded is True

    monkeypatch.setattr(capturer_module.windows, "is_occluded", lambda *a, **k: False)
    checked = WindowCapturer(CaptureOptions(backend="screen")).capture(
        1234, CaptureRegion(0, 0, 10, 10)
    )
    assert checked.occluded is False


def test_capturer_rejects_window_whose_client_is_offscreen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只剩标题栏在桌面内时，客户区已完全出屏，必须拒绝而不是返回旧像素。

    修复前用 ``frame_rect`` 判断：边框仍与桌面相交，校验通过，随后 GDI 用一个
    完全越界的源矩形 BitBlt，返回成功但不写入复用 DIB。
    """
    window = _window(
        frame_rect=(1900, 60, 816, 639),
        client_origin=(1930, 100),
        screen_width=800,
        screen_height=600,
    )
    _patch_window(monkeypatch, window)
    screen = capturer_module._win32.virtual_screen_rect()
    assert window.frame_rect[0] < screen[0] + screen[2]
    assert window.client_origin[0] >= screen[0] + screen[2]
    with pytest.raises(WindowOutOfScreenError):
        WindowCapturer(CaptureOptions(backend="screen")).capture(
            1234, CaptureRegion(0, 0, 10, 10)
        )


def test_gdi_screen_backend_rejects_partially_offscreen_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """源矩形部分越界时 GDI 只写重叠部分，必须显式报错而不是返回残留像素。"""
    backend = gdi_module.GdiScreenBackend()
    backend.open(_window())
    monkeypatch.setattr(
        gdi_module.windows,
        "client_to_screen_rect",
        lambda _window, region: (1900, 1070, region.width, region.height),
    )
    monkeypatch.setattr(
        gdi_module._win32, "virtual_screen_rect", lambda: (0, 0, 1920, 1080)
    )
    with pytest.raises(CaptureRegionError):
        backend.capture(CaptureRegion(0, 0, 40, 40), space="screen")


# ------------------------------------------------------------------ DXGI


class _FakeSession:
    """替身复制会话：记录抓取区域并返回固定像素。"""

    def __init__(
        self, output_rect: tuple[int, int, int, int] = (0, 0, 1920, 1080)
    ) -> None:
        self.output_rect = output_rect
        self.opened = True
        self.calls: list[tuple[int, int, int, int]] = []
        self.closed = False

    def grab(self, region: tuple[int, int, int, int], timeout_ms: int = 0) -> bytes:
        """记录区域并返回对应像素。"""
        self.calls.append(region)
        return bytes([0x11, 0x22, 0x33, 0xFF]) * (region[2] * region[3])

    def close(self) -> None:
        """标记为已关闭。"""
        self.closed = True
        self.opened = False


class _LostSession(_FakeSession):
    """每次都抛出复制失效的替身。"""

    def grab(self, region: tuple[int, int, int, int], timeout_ms: int = 0) -> bytes:
        """抛出 :class:`AccessLostError`。"""
        raise AccessLostError("桌面复制失效")


def _dxgi_backend_with(session: _FakeSession) -> dxgi_module.DxgiDesktopBackend:
    """构造一个已绑定窗口、并塞入指定会话的后端。"""
    backend = dxgi_module.DxgiDesktopBackend()
    backend.open(_window())
    backend._session = session  # type: ignore[assignment]
    return backend


def test_dxgi_backend_maps_screen_rect_to_output_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    backend = _dxgi_backend_with(session)
    monkeypatch.setattr(
        dxgi_module.windows,
        "client_to_screen_rect",
        lambda _window, region: (150, 90, region.width, region.height),
    )
    frame = backend.capture(CaptureRegion(0, 0, 10, 10), space="screen")
    assert session.calls == [(150, 90, 10, 10)]
    assert frame.backend == "dxgi"
    assert frame.space == SPACE_SCREEN
    assert len(frame.data) == 10 * 10 * 4


def test_dxgi_backend_subtracts_secondary_output_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(output_rect=(-1920, 0, 1920, 1080))
    backend = _dxgi_backend_with(session)
    monkeypatch.setattr(
        dxgi_module.windows,
        "client_to_screen_rect",
        lambda _window, region: (-1800, 100, region.width, region.height),
    )
    backend.capture(CaptureRegion(0, 0, 120, 60), space="screen")
    assert session.calls == [(120, 100, 120, 60)]


def test_dxgi_backend_rebuilds_after_access_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _LostSession()
    second = _FakeSession()
    sessions = iter([first, second])
    backend = _dxgi_backend_with(first)
    monkeypatch.setattr(backend, "_ensure_session", lambda _point: next(sessions))
    monkeypatch.setattr(
        dxgi_module.windows,
        "client_to_screen_rect",
        lambda _window, region: (0, 0, region.width, region.height),
    )
    frame = backend.capture(CaptureRegion(0, 0, 10, 10), space="screen")
    assert first.closed is True
    assert second.calls == [(0, 0, 10, 10)]
    assert frame.backend == "dxgi"


def test_dxgi_backend_rejects_empty_region() -> None:
    backend = _dxgi_backend_with(_FakeSession())
    with pytest.raises(CaptureRegionError):
        backend.capture(CaptureRegion(0, 0, 0, 10), space="screen")


def test_dxgi_backend_reports_scaled_size_for_virtualized_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DPI 虚拟化窗口下，帧宽高必须是换算后的屏幕像素，而不是客户区逻辑尺寸。

    修复前这里用 ``region.width``，而像素来自放大后的矩形，``ScreenFrame`` 的
    长度校验会抛 ValueError（不是 CaptureError），直接击穿 auto 的降级链。
    """
    session = _FakeSession()
    backend = _dxgi_backend_with(session)
    monkeypatch.setattr(
        dxgi_module.windows,
        "client_to_screen_rect",
        lambda _window, region: (
            100,
            80,
            region.width * 5 // 4,
            region.height * 5 // 4,
        ),
    )
    frame = backend.capture(CaptureRegion(0, 0, 320, 240), space="screen")
    assert (frame.width, frame.height) == (400, 300)
    assert len(frame.data) == 400 * 300 * 4
    assert session.calls == [(100, 80, 400, 300)]


# ------------------------------------------------------------------- WGC

_WGC_FRAME_SIZE = (902, 732)
_WGC_CLIENT_ORIGIN = (158, 151)
_WGC_FRAME_RECT = (157, 120, 902, 732)


def _wgc_window() -> WindowInfo:
    """与真机一致的窗口快照：客户区 900×700、帧 902×732。"""
    return _window(client_origin=_WGC_CLIENT_ORIGIN, frame_rect=_WGC_FRAME_RECT)


def _wgc_buffer(width: int, height: int) -> np.ndarray:
    """以坐标编码像素的 BGRA 缓冲，便于校验裁剪落点。"""
    buffer = np.empty((height, width, 4), dtype=np.uint8)
    buffer[..., 0] = (np.arange(width) % 256).astype(np.uint8)[None, :]
    buffer[..., 1] = (np.arange(height) % 256).astype(np.uint8)[:, None]
    buffer[..., 2] = 0
    buffer[..., 3] = 255
    return buffer


class _FakeControl:
    """替身捕获控制对象。"""

    def __init__(self) -> None:
        self.stopped = False

    def is_finished(self) -> bool:
        """是否已停止。"""
        return self.stopped

    def stop(self) -> None:
        """标记停止。"""
        self.stopped = True

    def wait(self) -> None:
        """立即返回。"""


class _FakeCapture:
    """替身 ``WindowsCapture``：启动时同步投递一帧。"""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.handlers: dict[str, Any] = {}
        self.control = _FakeControl()

    def event(self, handler: Any) -> Any:
        """按函数名记录回调。"""
        self.handlers[handler.__name__] = handler
        return handler

    def start_free_threaded(self) -> _FakeControl:
        """投递一帧后返回控制对象。"""
        width, height = _WGC_FRAME_SIZE
        frame = SimpleNamespace(
            width=width, height=height, frame_buffer=_wgc_buffer(width, height)
        )
        self.handlers["on_frame_arrived"](frame, None)
        return self.control


def _wgc_backend(monkeypatch: pytest.MonkeyPatch) -> Any:
    """构造一个使用替身捕获类的后端。"""
    monkeypatch.setattr(wgc_module, "_capture_class", lambda: _FakeCapture)
    backend = wgc_module.WgcWindowBackend(fresh_timeout_ms=0)
    backend.open(_wgc_window())
    return backend


def test_wgc_backend_crops_with_client_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _wgc_backend(monkeypatch)
    frame = backend.capture(CaptureRegion(600, 100, 250, 200), space=SPACE_CLIENT)
    assert frame.backend == "wgc"
    assert frame.space == SPACE_CLIENT
    assert (frame.width, frame.height) == (250, 200)
    # 客户区偏移 = client_origin - frame_rect 左上角 = (1, 31)
    assert frame.data[:4] == bytes([(600 + 1) % 256, (100 + 31) % 256, 0, 255])
    backend.close()


def test_wgc_backend_rejects_screen_space(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _wgc_backend(monkeypatch)
    with pytest.raises(ValueError):
        backend.capture(CaptureRegion(0, 0, 10, 10), space=SPACE_SCREEN)
    backend.close()


def test_wgc_backend_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing() -> object:
        raise CaptureUnavailableError("未安装 windows-capture")

    monkeypatch.setattr(wgc_module, "_capture_class", _missing)
    backend = wgc_module.WgcWindowBackend()
    with pytest.raises(CaptureUnavailableError):
        backend.open(_wgc_window())


def test_wgc_backend_raises_after_window_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _wgc_backend(monkeypatch)
    backend.on_closed()
    with pytest.raises(CaptureBackendError):
        backend.capture(CaptureRegion(0, 0, 10, 10), space=SPACE_CLIENT)
    backend.close()


def test_wgc_backend_rejects_region_outside_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _wgc_backend(monkeypatch)
    with pytest.raises(CaptureRegionError):
        backend.capture(CaptureRegion(900, 700, 10, 10), space=SPACE_CLIENT)
    backend.close()


def test_capturer_uses_wgc_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    window = _window()
    _patch_window(monkeypatch, window)
    monkeypatch.setattr(
        capturer_module.WgcWindowBackend, "open", lambda self, _window: None
    )
    monkeypatch.setattr(
        capturer_module.WgcWindowBackend,
        "capture",
        lambda self, region, space: _frame(
            window,
            width=region.width,
            height=region.height,
            backend="wgc",
            space=SPACE_CLIENT,
        ),
    )
    frame = WindowCapturer(CaptureOptions(backend="wgc")).capture(
        1234, CaptureRegion(0, 0, 10, 10)
    )
    assert frame.backend == "wgc"
    assert frame.degraded is False


# --------------------------------------------------------------------- 真机

_REAL_DESKTOP = (
    sys.platform == "win32" and os.environ.get("SHEEPBOX_REAL_DESKTOP") == "1"
)


@pytest.mark.skipif(
    not _REAL_DESKTOP, reason="需要真实交互桌面，设置 SHEEPBOX_REAL_DESKTOP=1"
)
def test_real_window_capture_smoke() -> None:  # pragma: no cover - 依赖真实桌面
    """在真实桌面上抓一个 QWidget，验证尺寸与像素。"""
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":  # pragma: no cover
        pytest.skip("offscreen 平台没有真实窗口句柄")

    from PySide6.QtWidgets import QApplication, QWidget

    from service.capture import _win32
    from service.capture.windows import get_window_info

    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    widget.setStyleSheet("background: #cc2222;")
    widget.resize(400, 300)
    widget.show()
    app.processEvents()
    hwnd = _win32.root_window(int(widget.winId()))
    info = get_window_info(hwnd)
    with WindowCapturer() as capturer:
        frame = capturer.capture(
            hwnd, CaptureRegion.full(info.client_width, info.client_height)
        )
    assert frame.width == info.client_width
    assert frame.height == info.client_height
    assert blank_ratio(frame.data) < 0.995

    # 桌面复制路径：同样的区域应给出同样尺寸，backend 标记为 dxgi
    with WindowCapturer(CaptureOptions(backend="dxgi")) as capturer:
        dxgi_frame = capturer.capture(
            hwnd, CaptureRegion.full(info.client_width, info.client_height)
        )
    assert dxgi_frame.backend == "dxgi"
    assert dxgi_frame.width == info.client_width
    assert dxgi_frame.height == info.client_height

    # 单窗口捕获：抓窗口自身内容，尺寸正好等于客户区
    try:
        with WindowCapturer(CaptureOptions(backend="wgc")) as capturer:
            wgc_frame = capturer.capture(
                hwnd, CaptureRegion.full(info.client_width, info.client_height)
            )
    except CaptureUnavailableError:
        pytest.skip("当前环境不支持 WGC")
    assert wgc_frame.backend == "wgc"
    assert wgc_frame.space == SPACE_CLIENT
    assert (wgc_frame.width, wgc_frame.height) == (
        info.client_width,
        info.client_height,
    )
    widget.close()
