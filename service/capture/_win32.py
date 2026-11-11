"""窗口截图的原生 API 绑定（ctypes）。

只做「调系统 DLL + 拆结构体」：窗口查询、屏幕 DC、DIB 缓冲、位块传输。把返回值
整理成数据模型、判断该用哪个后端的职责在 :mod:`service.capture.windows` 与
:mod:`service.capture.capturer`。

零第三方依赖，与 ``service.sysinfo._win32`` 的组织方式一致；非 Windows 平台在
导入时即报错，由上层按平台判断后惰性导入。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from dataclasses import dataclass

if sys.platform != "win32":  # pragma: no cover - 仅 Windows 部署
    raise ImportError("service.capture._win32 仅支持 Windows")

__all__ = [
    "DibSurface",
    "NativeApiError",
    "bitblt",
    "class_name",
    "client_origin",
    "client_rect",
    "dpi_for_window",
    "ensure_dpi_aware",
    "enum_windows",
    "ex_style",
    "foreground_window",
    "get_dc",
    "is_minimized",
    "is_visible",
    "is_window",
    "last_error",
    "make_surface",
    "print_window",
    "process_id",
    "process_name",
    "release_dc",
    "root_window",
    "screen_size",
    "virtual_screen_rect",
    "window_below",
    "window_frame_rect",
    "window_from_point",
    "window_text",
]

# --------------------------------------------------------------------------
# 常量与错误
# --------------------------------------------------------------------------

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0

_GA_ROOT = 2
_GW_HWNDNEXT = 2
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_PW_RENDERFULLCONTENT = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_ERROR_ACCESS_DENIED = 5


class NativeApiError(RuntimeError):
    """底层 Win32 / DWM 调用失败，``code`` 为 ``GetLastError`` 值（0 表示不适用）。"""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


def last_error() -> int:
    """读取当前线程的 Win32 错误码。"""
    return ctypes.get_last_error()


def _hex(code: int) -> str:
    """把错误码格式化成固定宽度十六进制，便于检索。"""
    return f"0x{code & 0xFFFFFFFF:08X}"


# --------------------------------------------------------------------------
# DLL 与函数原型
# --------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.IsWindow.argtypes = [wt.HWND]
user32.IsWindow.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.IsIconic.argtypes = [wt.HWND]
user32.IsIconic.restype = wt.BOOL
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.restype = wt.BOOL
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.ClientToScreen.restype = wt.BOOL
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.WindowFromPoint.argtypes = [wt.POINT]
user32.WindowFromPoint.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext.restype = wt.BOOL
user32.GetDpiForWindow.argtypes = [wt.HWND]
user32.GetDpiForWindow.restype = wt.UINT
user32.GetDpiForSystem.restype = wt.UINT
user32.GetWindowDpiAwarenessContext.argtypes = [wt.HWND]
user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.PrintWindow.restype = wt.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateDIBSection.argtypes = [
    wt.HDC,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
    wt.HANDLE,
    wt.DWORD,
]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.DeleteDC.restype = wt.BOOL
gdi32.BitBlt.argtypes = [
    wt.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wt.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wt.DWORD,
]
gdi32.BitBlt.restype = wt.BOOL

dwmapi.DwmGetWindowAttribute.argtypes = [
    wt.HWND,
    wt.DWORD,
    ctypes.c_void_p,
    wt.DWORD,
]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE,
    wt.DWORD,
    wt.LPWSTR,
    ctypes.POINTER(wt.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL


# --------------------------------------------------------------------------
# DIB 表面
# --------------------------------------------------------------------------


class _BitmapInfoHeader(ctypes.Structure):
    """``BITMAPINFOHEADER``。"""

    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    """``BITMAPINFO``（32bpp 时调色板不用，但保留结构以匹配 API 签名）。"""

    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wt.DWORD * 3)]


@dataclass
class DibSurface:
    """一块 32bpp、自上而下的 DIB 及其兼容 DC，用于接收 ``BitBlt`` 结果。

    Attributes:
        width: 宽。
        height: 高。
        dc: 内存 DC。
        _bitmap: DIB 句柄（``DeleteObject`` 释放）。
        _bits: 像素首址。
    """

    width: int
    height: int
    dc: int
    _bitmap: int
    _bits: int

    @property
    def stride(self) -> int:
        """每行字节数。"""
        return self.width * 4

    def read(self) -> bytes:
        """把像素拷成独立 ``bytes``。

        Returns:
            长度 ``width * height * 4`` 的 BGRA 数据。
        """
        return ctypes.string_at(self._bits, self.width * self.height * 4)

    def close(self) -> None:
        """释放 DIB 与 DC；重复调用安全。"""
        if self._bitmap:
            gdi32.DeleteObject(wt.HANDLE(self._bitmap))
            self._bitmap = 0
        if self.dc:
            gdi32.DeleteDC(wt.HDC(self.dc))
            self.dc = 0

    def __del__(self) -> None:
        """对象被回收时兜底释放。"""
        self.close()


def make_surface(width: int, height: int) -> DibSurface:
    """创建一块 32bpp top-down DIB 表面。

    Args:
        width: 宽，必须为正。
        height: 高，必须为正。

    Returns:
        新表面，使用完必须 ``close()``。

    Raises:
        NativeApiError: DC 或 DIB 创建失败。
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"非法表面尺寸: {width}x{height}")
    dc = gdi32.CreateCompatibleDC(None)
    if not dc:
        raise NativeApiError("CreateCompatibleDC 失败", last_error())

    header = _BitmapInfoHeader()
    header.biSize = ctypes.sizeof(_BitmapInfoHeader)
    header.biWidth = width
    header.biHeight = -height  # 负高度即 top-down，省去翻转
    header.biPlanes = 1
    header.biBitCount = 32
    info = _BitmapInfo(bmiHeader=header)

    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(
        wt.HDC(dc),
        ctypes.byref(info),
        DIB_RGB_COLORS,
        ctypes.byref(bits),
        None,
        0,
    )
    if not bitmap or not bits.value:
        gdi32.DeleteDC(wt.HDC(dc))
        raise NativeApiError("CreateDIBSection 失败", last_error())
    if not gdi32.SelectObject(wt.HDC(dc), wt.HGDIOBJ(bitmap)):
        gdi32.DeleteObject(wt.HANDLE(bitmap))
        gdi32.DeleteDC(wt.HDC(dc))
        raise NativeApiError("SelectObject 失败", last_error())
    return DibSurface(width, height, int(dc), int(bitmap), bits.value)


# --------------------------------------------------------------------------
# 窗口查询
# --------------------------------------------------------------------------


def ensure_dpi_aware() -> tuple[bool, int]:
    """把进程设为 per-monitor v2 DPI 感知。

    ``E_ACCESSDENIED``（进程已设置过，Qt6 通常已设）视为成功。

    Returns:
        ``(是否满足 per-monitor v2, 错误码)``；错误码 0 表示无人为失败。
    """
    if user32.SetProcessDpiAwarenessContext(
        _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    ):
        return True, 0
    code = last_error()
    if code == _ERROR_ACCESS_DENIED:
        return True, 0
    return False, code


def is_window(hwnd: int) -> bool:
    """句柄是否为有效窗口。"""
    return bool(user32.IsWindow(wt.HWND(hwnd)))


def is_visible(hwnd: int) -> bool:
    """窗口是否可见。"""
    return bool(user32.IsWindowVisible(wt.HWND(hwnd)))


def is_minimized(hwnd: int) -> bool:
    """窗口是否最小化。"""
    return bool(user32.IsIconic(wt.HWND(hwnd)))


def client_rect(hwnd: int) -> tuple[int, int]:
    """返回客户区尺寸 ``(宽, 高)``。

    Raises:
        NativeApiError: ``GetClientRect`` 失败。
    """
    rect = wt.RECT()
    if not user32.GetClientRect(wt.HWND(hwnd), ctypes.byref(rect)):
        raise NativeApiError("GetClientRect 失败", last_error())
    return rect.right - rect.left, rect.bottom - rect.top


def client_origin(hwnd: int) -> tuple[int, int]:
    """返回客户区左上角的屏幕坐标。

    Raises:
        NativeApiError: ``ClientToScreen`` 失败。
    """
    point = wt.POINT(0, 0)
    if not user32.ClientToScreen(wt.HWND(hwnd), ctypes.byref(point)):
        raise NativeApiError("ClientToScreen 失败", last_error())
    return point.x, point.y


def window_frame_rect(hwnd: int) -> tuple[int, int, int, int]:
    """返回窗框屏幕矩形 ``(left, top, width, height)``。

    优先 ``DwmGetWindowAttribute`` 的扩展框（排除阴影与圆角留白），拿不到退
    ``GetWindowRect``。

    Raises:
        NativeApiError: 两种取法都失败。
    """
    rect = wt.RECT()
    status = dwmapi.DwmGetWindowAttribute(
        wt.HWND(hwnd),
        _DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if status != 0 and not user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect)):
        raise NativeApiError("GetWindowRect 失败", last_error())
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def class_name(hwnd: int) -> str:
    """返回窗口类名；失败时为空串。"""
    buffer = ctypes.create_unicode_buffer(256)
    length = user32.GetClassNameW(wt.HWND(hwnd), buffer, len(buffer))
    return buffer.value[:length] if length else ""


def window_text(hwnd: int) -> str:
    """返回窗口标题；失败时为空串。"""
    buffer = ctypes.create_unicode_buffer(512)
    length = user32.GetWindowTextW(wt.HWND(hwnd), buffer, len(buffer))
    return buffer.value[:length] if length else ""


def ex_style(hwnd: int) -> int:
    """返回窗口扩展样式；失败时为 0。"""
    value = user32.GetWindowLongPtrW(wt.HWND(hwnd), _GWL_EXSTYLE)
    return int(value) if value else 0


def has_tool_window_style(hwnd: int) -> bool:
    """窗口是否带 ``WS_EX_TOOLWINDOW``（枚举时应排除）。"""
    return bool(ex_style(hwnd) & _WS_EX_TOOLWINDOW)


def dpi_for_window(hwnd: int) -> int:
    """返回窗口 DPI；取不到时为 96。"""
    dpi = user32.GetDpiForWindow(wt.HWND(hwnd))
    return int(dpi) if dpi else 96


def dpi_for_system() -> int:
    """返回系统（主屏）DPI；取不到时为 96。"""
    dpi = user32.GetDpiForSystem()
    return int(dpi) if dpi else 96


def window_dpi_awareness(hwnd: int) -> int:
    """返回窗口的 DPI 感知级别：0=UNAWARE、1=SYSTEM、2=PER_MONITOR。

    取不到时按 2 处理（视为已感知，调用方因此不会额外缩放），避免放大错误。

    Returns:
        感知级别整数。
    """
    context = user32.GetWindowDpiAwarenessContext(wt.HWND(hwnd))
    if not context:
        return 2
    level = user32.GetAwarenessFromDpiAwarenessContext(ctypes.c_void_p(context))
    if level < 0:
        return 2
    return int(level)


def process_id(hwnd: int) -> int:
    """返回窗口所属进程 ID。"""
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def process_name(pid: int) -> str:
    """返回进程可执行文件名（不含目录）；打不开进程时为空串。"""
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wt.DWORD(260)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return ""
        path = buffer.value[: size.value]
    finally:
        kernel32.CloseHandle(handle)
    return path.replace("/", "\\").rsplit("\\", 1)[-1]


def root_window(hwnd: int) -> int:
    """把子窗口提升到顶层窗口；失败时返回原句柄。"""
    root = user32.GetAncestor(wt.HWND(hwnd), _GA_ROOT)
    return int(root) if root else hwnd


def window_from_point(x: int, y: int) -> int:
    """返回屏幕点下方的窗口句柄（可能是子窗口）；无窗口时为 0。"""
    handle = user32.WindowFromPoint(wt.POINT(int(x), int(y)))
    return int(handle) if handle else 0


def window_below(hwnd: int) -> int:
    """返回 z-order 中位于 ``hwnd`` 下方的下一个顶层窗口；没有时为 0。

    用于「排除覆盖层自身后，找真正被覆盖的那个窗口」：``WindowFromPoint`` 只会
    给出最上面那个，沿 ``GW_HWNDNEXT`` 往下走才能拿到下一层。

    Args:
        hwnd: 起始窗口句柄。

    Returns:
        下一个窗口句柄；已到最底层时为 0。
    """
    handle = user32.GetWindow(wt.HWND(hwnd), wt.UINT(_GW_HWNDNEXT))
    return int(handle) if handle else 0


def foreground_window() -> int:
    """返回前台窗口句柄；没有时为 0。"""
    handle = user32.GetForegroundWindow()
    return int(handle) if handle else 0


def screen_size() -> tuple[int, int]:
    """返回主屏尺寸 ``(宽, 高)``（物理像素，前提是进程已 DPI 感知）。"""
    return (
        int(user32.GetSystemMetrics(0)),
        int(user32.GetSystemMetrics(1)),
    )


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """返回虚拟桌面（所有显示器并集）的矩形 ``(left, top, width, height)``。"""
    return (
        int(user32.GetSystemMetrics(76)),
        int(user32.GetSystemMetrics(77)),
        int(user32.GetSystemMetrics(78)),
        int(user32.GetSystemMetrics(79)),
    )


_WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def enum_windows() -> list[int]:
    """按 z-order（顶到底）返回所有顶层窗口句柄，不做任何过滤。

    Returns:
        窗口句柄列表。
    """
    handles: list[int] = []

    @_WNDENUMPROC
    def _callback(hwnd: int, _lparam: int) -> bool:
        handles.append(int(hwnd))
        return True

    user32.EnumWindows.argtypes = [_WNDENUMPROC, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.EnumWindows(_callback, 0)
    return handles


# --------------------------------------------------------------------------
# DC 与位块传输
# --------------------------------------------------------------------------


def get_dc(hwnd: int) -> int:
    """取得窗口（``hwnd``）或整个屏幕（``hwnd=0``）的 DC。

    Raises:
        NativeApiError: ``GetDC`` 返回空。
    """
    dc = user32.GetDC(wt.HWND(hwnd))
    if not dc:
        raise NativeApiError(f"GetDC({hwnd}) 失败", last_error())
    return int(dc)


def release_dc(hwnd: int, dc: int) -> None:
    """释放 :func:`get_dc` 取得的 DC。"""
    if dc:
        user32.ReleaseDC(wt.HWND(hwnd), wt.HDC(dc))


def bitblt(
    dst_dc: int,
    src_dc: int,
    src_x: int,
    src_y: int,
    width: int,
    height: int,
) -> None:
    """把源 DC 的一块像素拷到目标 DC 的 ``(0, 0)``。

    Args:
        dst_dc: 目标 DC（通常是 :class:`DibSurface` 的 DC）。
        src_dc: 源 DC。
        src_x: 源左偏移。
        src_y: 源上偏移。
        width: 宽。
        height: 高。

    Raises:
        NativeApiError: ``BitBlt`` 失败。
    """
    if not gdi32.BitBlt(
        wt.HDC(dst_dc),
        0,
        0,
        width,
        height,
        wt.HDC(src_dc),
        src_x,
        src_y,
        SRCCOPY,
    ):
        raise NativeApiError("BitBlt 失败", last_error())


def print_window(hwnd: int, dst_dc: int) -> bool:
    """用 ``PrintWindow(PW_RENDERFULLCONTENT)`` 把窗口内容画到目标 DC。"""
    return bool(
        user32.PrintWindow(wt.HWND(hwnd), wt.HDC(dst_dc), _PW_RENDERFULLCONTENT)
    )
