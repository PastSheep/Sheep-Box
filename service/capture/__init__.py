"""窗口区域截图基础能力模块。

与 ``service/ocr``、``service/sysinfo`` 平级：输入窗口句柄 + 客户区区域，输出
原始像素（BGRA、自上而下）与元数据；不做 OCR、不做定时调度、不做编码落盘、
不读写业务配置、不导入 PySide6。

能力给全、业务按需：模块提供多种抓取后端（屏幕帧 / 窗口表面，DXGI 与 WGC 为
后续扩展），用 ``CaptureOptions.backend`` 选择，失败与降级通过 ``ScreenFrame``
的 ``degraded`` / ``occluded`` 如实标记。

``WindowCapturer`` 采用 PEP 562 按需导出：只取数据模型时不加载 ctypes 绑定。
"""

from typing import TYPE_CHECKING

from service.capture.models import (
    BackendCapabilities,
    CaptureOptions,
    CaptureRegion,
    NormalizedRegion,
    ScreenFrame,
    WindowInfo,
)

if TYPE_CHECKING:  # 仅类型检查可见，运行时不触发后端导入
    from common.exceptions import (
        CaptureBackendError,
        CaptureError,
        CaptureOccludedError,
        CaptureRegionError,
        CaptureUnavailableError,
        WindowNotFoundError,
        WindowNotVisibleError,
        WindowOutOfScreenError,
    )
    from service.capture.capturer import WindowCapturer
    from service.capture.windows import (
        get_window_info,
        hwnd_from_point,
        is_occluded,
        list_windows,
        region_from_screen,
    )

__all__ = [
    "BackendCapabilities",
    "CaptureBackendError",
    "CaptureError",
    "CaptureOccludedError",
    "CaptureOptions",
    "CaptureRegion",
    "CaptureRegionError",
    "CaptureUnavailableError",
    "NormalizedRegion",
    "ScreenFrame",
    "WindowCapturer",
    "WindowInfo",
    "WindowNotFoundError",
    "WindowNotVisibleError",
    "WindowOutOfScreenError",
    "get_window_info",
    "hwnd_from_point",
    "is_occluded",
    "list_windows",
    "region_from_screen",
]

_EXCEPTION_NAMES = frozenset(
    {
        "CaptureBackendError",
        "CaptureError",
        "CaptureOccludedError",
        "CaptureRegionError",
        "CaptureUnavailableError",
        "WindowNotFoundError",
        "WindowNotVisibleError",
        "WindowOutOfScreenError",
    }
)

_WINDOW_FUNCTION_NAMES = frozenset(
    {
        "get_window_info",
        "hwnd_from_point",
        "is_occluded",
        "list_windows",
        "region_from_screen",
    }
)


def __getattr__(name: str) -> object:
    """按需导入门面、窗口查询函数与异常（PEP 562）。

    Args:
        name: 属性名。

    Returns:
        对应的导出对象。

    Raises:
        AttributeError: 属性不存在。
    """
    if name == "WindowCapturer":
        from service.capture.capturer import WindowCapturer

        return WindowCapturer
    if name in _EXCEPTION_NAMES:
        from common import exceptions

        return getattr(exceptions, name)
    if name in _WINDOW_FUNCTION_NAMES:
        from service.capture import windows

        return getattr(windows, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
