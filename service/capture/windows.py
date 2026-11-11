"""窗口枚举与查询，以及客户区与屏幕坐标之间的换算。

只做查询与纯计算，不抓像素；抓取在 :mod:`service.capture.backends`。

两类尺寸必须分清（见 ``WindowInfo``）：

- ``client_width/height``：窗口表面口径。DPI-unaware 窗口会拿到逻辑尺寸；
- ``screen_width/height``：客户区在屏幕上的实际占位（物理像素）。

窗口被系统位图拉伸时两者不等，区域换算必须按调用方选定的口径进行。
"""

from __future__ import annotations

import os

from common.exceptions import WindowNotFoundError
from service.capture import _win32
from service.capture.models import CaptureRegion, WindowInfo

__all__ = [
    "client_to_screen_rect",
    "get_window_info",
    "hwnd_from_point",
    "is_occluded",
    "list_windows",
    "region_from_screen",
]

# 桌面壳窗口：没有可截取内容，枚举时排除
_DESKTOP_CLASS_NAMES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd"})


def _build_window_info(hwnd: int) -> WindowInfo:
    """采集单个窗口的全部描述字段。

    Args:
        hwnd: 窗口句柄。

    Returns:
        窗口信息。

    Raises:
        WindowNotFoundError: 窗口已销毁或关键查询失败。
    """
    try:
        client_width, client_height = _win32.client_rect(hwnd)
        origin_x, origin_y = _win32.client_origin(hwnd)
        frame_rect = _win32.window_frame_rect(hwnd)
    except _win32.NativeApiError as exc:
        raise WindowNotFoundError(f"窗口 {hwnd} 查询失败：{exc}") from exc

    dpi = _win32.dpi_for_window(hwnd)
    if _win32.window_dpi_awareness(hwnd) == 0:
        # DPI-unaware 窗口被系统位图拉伸：屏幕占位 = 逻辑尺寸 × 系统缩放
        scale = _win32.dpi_for_system() / 96.0
        screen_width = round(client_width * scale)
        screen_height = round(client_height * scale)
    else:
        screen_width, screen_height = client_width, client_height

    return WindowInfo(
        hwnd=hwnd,
        title=_win32.window_text(hwnd),
        class_name=_win32.class_name(hwnd),
        process_id=_win32.process_id(hwnd),
        process_name=_win32.process_name(_win32.process_id(hwnd)),
        client_width=client_width,
        client_height=client_height,
        screen_width=screen_width,
        screen_height=screen_height,
        dpi=dpi,
        visible=_win32.is_visible(hwnd),
        minimized=_win32.is_minimized(hwnd),
        frame_rect=frame_rect,
        client_origin=(origin_x, origin_y),
    )


def get_window_info(hwnd: int) -> WindowInfo:
    """查询单个窗口的描述。

    Args:
        hwnd: 窗口句柄。

    Returns:
        窗口信息。

    Raises:
        WindowNotFoundError: 句柄无效或窗口已销毁。
    """
    if not hwnd or not _win32.is_window(hwnd):
        raise WindowNotFoundError(f"窗口句柄无效或已销毁：{hwnd}")
    return _build_window_info(hwnd)


def list_windows(
    *,
    visible_only: bool = True,
    exclude_tool_windows: bool = True,
    exclude_own_process: bool = True,
) -> tuple[WindowInfo, ...]:
    """按 z-order（顶到底）枚举顶层窗口。

    Args:
        visible_only: 只保留可见窗口。
        exclude_tool_windows: 排除 ``WS_EX_TOOLWINDOW`` 工具窗口。
        exclude_own_process: 排除本进程窗口。

    Returns:
        窗口信息元组；单个窗口查询失败时跳过该项。
    """
    own_pid = os.getpid()
    result: list[WindowInfo] = []
    for hwnd in _win32.enum_windows():
        try:
            if exclude_own_process and _win32.process_id(hwnd) == own_pid:
                continue
            if exclude_tool_windows and _win32.has_tool_window_style(hwnd):
                continue
            if _win32.class_name(hwnd) in _DESKTOP_CLASS_NAMES:
                continue
            if visible_only and not _win32.is_visible(hwnd):
                continue
            info = _build_window_info(hwnd)
        except _win32.NativeApiError:
            continue
        except WindowNotFoundError:
            continue
        if not info.title:
            continue
        result.append(info)
    return tuple(result)


def hwnd_from_point(x: int, y: int) -> int:
    """返回屏幕点下方的顶层窗口句柄。

    Args:
        x: 屏幕物理 X。
        y: 屏幕物理 Y。

    Returns:
        顶层窗口句柄；该处没有窗口时为 0。
    """
    handle = _win32.window_from_point(x, y)
    return _win32.root_window(handle) if handle else 0


def client_to_screen_rect(
    window: WindowInfo, region: CaptureRegion
) -> tuple[int, int, int, int]:
    """把客户区坐标区域换算成屏幕物理像素矩形。

    Args:
        window: 目标窗口。
        region: 客户区口径的区域。

    Returns:
        ``(left, top, width, height)``。
    """
    scale_x = window.screen_width / window.client_width if window.client_width else 1.0
    scale_y = (
        window.screen_height / window.client_height if window.client_height else 1.0
    )
    left = window.client_origin[0] + round(region.x * scale_x)
    top = window.client_origin[1] + round(region.y * scale_y)
    return left, top, round(region.width * scale_x), round(region.height * scale_y)


def region_from_screen(
    window: WindowInfo,
    screen_rect: tuple[int, int, int, int],
    *,
    clamp: bool = True,
) -> CaptureRegion:
    """把屏幕物理像素矩形换算成客户区口径的区域。

    Args:
        window: 目标窗口。
        screen_rect: ``(left, top, width, height)``，屏幕物理像素。
        clamp: 是否裁剪到客户区内。

    Returns:
        客户区口径区域；``clamp`` 为假时可能越界（宽高仍为非负）。
    """
    scale_x = window.client_width / window.screen_width if window.screen_width else 1.0
    scale_y = (
        window.client_height / window.screen_height if window.screen_height else 1.0
    )
    region = CaptureRegion(
        round((screen_rect[0] - window.client_origin[0]) * scale_x),
        round((screen_rect[1] - window.client_origin[1]) * scale_y),
        round(screen_rect[2] * scale_x),
        round(screen_rect[3] * scale_y),
    )
    if clamp:
        return region.clamp(window.client_width, window.client_height)
    return region


def is_occluded(
    window: WindowInfo, region: CaptureRegion, *, strict: bool = False
) -> bool:
    """判断区域中心点是否被其它窗口覆盖。

    屏幕口径下被覆盖时，截到的是遮挡者的内容而不是目标窗口，因此这是抓取前的
    必要校验。窗口自身的子窗口不算遮挡。

    Args:
        window: 目标窗口。
        region: 客户区口径区域（内部换算到屏幕）。
        strict: 为真时要求目标窗口必须是前台窗口；为假时只看中心点归谁。

    Returns:
        是否判定为被遮挡。
    """
    left, top, width, height = client_to_screen_rect(window, region)
    if width <= 0 or height <= 0:
        return False
    center_x = left + width // 2
    center_y = top + height // 2

    if strict:
        foreground = _win32.root_window(_win32.foreground_window())
        return foreground != window.hwnd

    owner = _win32.window_from_point(center_x, center_y)
    if not owner:
        return True
    return _win32.root_window(owner) != window.hwnd
