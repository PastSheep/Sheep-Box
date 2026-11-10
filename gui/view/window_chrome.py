"""Windows 原生窗口框架集成：去掉系统标题栏，保留系统的窗口行为。

为什么不是 ``Qt.FramelessWindowHint`` + 纯自绘：无边框窗口会同时丢掉 Aero
Snap、双击最大化、DWM 阴影、Win11 圆角、四角缩放热区与 Alt+Tab 的窗口外观，
这些都要自己补，补不齐。这里反过来做——**保留 ``WS_OVERLAPPEDWINDOW``**，
只在消息层动手：

- ``WM_NCCALCSIZE``：让客户区等于整个窗口，系统标题栏自然消失，但窗口样式
  与 DWM 装饰仍在；
- ``WM_NCHITTEST``：顶部标题栏区域返回 ``HTCAPTION``（拖动、双击最大化、贴边
  由系统完成），四边按 DPI 换算返回缩放热区，其余交给 Qt；
- ``DwmSetWindowAttribute``：Win11 的窗口圆角。

Qt 侧则声明为 ``FramelessWindowHint``：Qt 据此认为客户区等于整个窗口，最大化
按工作区计算、``mapToGlobal`` 也不会带偏；随后把 ``WS_THICKFRAME`` 等样式加回
窗口，DWM 阴影、贴边分屏与系统菜单不受影响。

这些都是逐消息判断，不做 ``WndProc`` 子类化：Qt 已经把窗口消息转给
``QWidget.nativeEvent``，在那里分工即可，出错也不会破坏窗口消息循环。

可通过环境变量 ``SHEEPBOX_NATIVE_TITLEBAR=0`` 退回系统标题栏（逃生口：
任何平台问题都能立刻恢复原生外观，不必改代码）。
"""

from __future__ import annotations

import ctypes
import logging
import os
from collections.abc import Callable
from ctypes import wintypes

logger = logging.getLogger(__name__)

__all__ = ["NativeFrame", "native_frame_enabled"]

_IS_WINDOWS = os.name == "nt"
_ENV_SWITCH = "SHEEPBOX_NATIVE_TITLEBAR"

WM_GETMINMAXINFO = 0x0024
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232

HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

SM_CXFRAME = 32
SM_CYFRAME = 33
SM_CXPADDEDBORDER = 92

GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

_BORDER_HITS = {
    HTLEFT,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
}


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _POINT),
    ]


if _IS_WINDOWS:  # pragma: no cover - 仅 Windows 上有意义
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    _user32.DefWindowProcW.restype = wintypes.LPARAM
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.IsZoomed.argtypes = [wintypes.HWND]
    _user32.IsZoomed.restype = wintypes.BOOL
    _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    _user32.GetDpiForWindow.restype = wintypes.UINT
    _user32.GetWindowLongPtrW.restype = ctypes.c_longlong
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_longlong
    _user32.SetWindowLongPtrW.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_longlong,
    ]
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL


def native_frame_enabled() -> bool:
    """当前是否应启用自绘标题栏（Windows + 未被环境变量关闭）。"""
    if not _IS_WINDOWS:
        return False
    return os.environ.get(_ENV_SWITCH, "1") != "0"


def _unpack_position(position: int) -> tuple[int, int]:
    """把 ``lParam`` 里的屏幕坐标拆成有符号的 x / y。"""
    x = position & 0xFFFF
    y = (position >> 16) & 0xFFFF
    if x >= 0x8000:
        x -= 0x10000
    if y >= 0x8000:
        y -= 0x10000
    return x, y


class NativeFrame:
    """把自绘标题栏接入原生窗口消息。

    Args:
        title_height: 顶部可拖动区域的高度（与自绘标题栏一致）。
        is_drag_region: 判断窗口坐标 ``(x, y)`` 是否落在可拖动区（排除导航项与
            窗口按钮，避免误拖）。
        on_size_move: 拖动/缩放开始与结束时回调（``True`` 开始、``False`` 结束），
            用于冻结毛玻璃重算。
    """

    def __init__(
        self,
        *,
        title_height: int,
        is_drag_region: Callable[[int, int], bool] | None = None,
        on_size_move: Callable[[bool], None] | None = None,
    ) -> None:
        self._title_height = max(0, int(title_height))
        self._is_drag_region = is_drag_region
        self._on_size_move = on_size_move
        self._hwnd = 0
        self._enabled = False
        self._border = 8

    @property
    def enabled(self) -> bool:
        """是否已成功接入（非 Windows 或已关闭时为 ``False``）。"""
        return self._enabled

    def install(self, hwnd: int) -> bool:
        """绑定窗口句柄并做一次性设置。

        两步缺一不可：

        1. Qt 侧已经是 ``FramelessWindowHint``（Qt 据此认为客户区 = 整个窗口，
        最大化按工作区算，``mapToGlobal`` 也不会偏移）；
        2. 把 ``WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX``
        加回窗口样式——否则丢掉 DWM 阴影、贴边分屏与系统菜单。
        """
        if not native_frame_enabled() or not hwnd:
            return False
        self._hwnd = int(hwnd)
        self._border = self._frame_border()
        try:
            self._restore_native_style()
        except Exception:
            logger.warning("恢复原生窗口样式失败", exc_info=True)
        try:
            preference = ctypes.c_int(DWMWCP_ROUND)
            _dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(self._hwnd),
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
        except Exception:  # Win10 及更早没有这个属性，忽略即可
            logger.debug("DWM 圆角设置失败（系统可能较旧）", exc_info=True)
        self._enabled = True
        return True

    def _restore_native_style(self) -> None:
        """给无边框窗口补回可缩放/系统菜单样式。"""
        hwnd = wintypes.HWND(self._hwnd)
        style = _user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style |= WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
        _user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        _user32.SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER,
        )

    # -------------------------------------------------------------- 消息处理

    def handle(self, message: int) -> tuple[bool, int]:
        """处理一条原生消息。

        Args:
            message: ``QWidget.nativeEvent`` 拿到的 ``MSG`` 地址。

        Returns:
            ``(是否已处理, 结果值)``；未处理时调用方应转交父类。
        """
        if not self._enabled:
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except Exception:
            logger.debug("无法读取原生消息", exc_info=True)
            return False, 0

        event = msg.message
        if event == WM_NCCALCSIZE:
            # 客户区 = 整个窗口：系统标题栏消失，但窗口样式与 DWM 装饰保留
            return (True, 0) if msg.wParam else (False, 0)
        if event == WM_NCHITTEST:
            return self._on_hit_test(int(msg.lParam))
        if event == WM_ENTERSIZEMOVE:
            if self._on_size_move is not None:
                self._on_size_move(True)
            return False, 0
        if event == WM_EXITSIZEMOVE:
            if self._on_size_move is not None:
                self._on_size_move(False)
            return False, 0
        return False, 0

    def _on_hit_test(self, address: int) -> tuple[bool, int]:
        """分配命中区：四边缩放、标题栏拖动，其余交给 Qt。"""
        try:
            x, y = _unpack_position(address)
            rect = _RECT()
            if not _user32.GetWindowRect(wintypes.HWND(self._hwnd), ctypes.byref(rect)):
                return False, 0
            if not _user32.IsZoomed(wintypes.HWND(self._hwnd)):
                border = self._border
                left = x < rect.left + border
                right = x >= rect.right - border
                top = y < rect.top + border
                bottom = y >= rect.bottom - border
                if top and left:
                    return True, HTTOPLEFT
                if top and right:
                    return True, HTTOPRIGHT
                if bottom and left:
                    return True, HTBOTTOMLEFT
                if bottom and right:
                    return True, HTBOTTOMRIGHT
                if left:
                    return True, HTLEFT
                if right:
                    return True, HTRIGHT
                if top:
                    return True, HTTOP
                if bottom:
                    return True, HTBOTTOM
            local_y = y - rect.top
            if 0 <= local_y < self._title_height:
                if self._is_drag_region is None or self._is_drag_region(
                    x - rect.left, local_y
                ):
                    return True, HTCAPTION
                return True, HTCLIENT
            return False, 0
        except Exception:
            logger.debug("命中区分配失败", exc_info=True)
            return False, 0

    def _frame_border(self) -> int:
        """按当前窗口 DPI 取缩放边框厚度。"""
        try:
            hwnd = wintypes.HWND(self._hwnd)
            dpi = _user32.GetDpiForWindow(hwnd) or 96
            getter = getattr(_user32, "GetSystemMetricsForDpi", None)
            if getter is None:
                return int(_user32.GetSystemMetrics(SM_CXFRAME)) or 8
            thickness = int(getter(SM_CXFRAME, dpi) + getter(SM_CXPADDEDBORDER, dpi))
            return thickness or 8
        except Exception:
            logger.debug("取边框厚度失败，回退 8px", exc_info=True)
            return 8
