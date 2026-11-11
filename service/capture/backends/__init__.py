"""抓取后端集合。

已实现：GDI 屏幕帧、GDI 窗口表面（含 ``PrintWindow`` 二次尝试）、DXGI 桌面复制、
WGC 单窗口捕获。能力差异由 :class:`service.capture.models.BackendCapabilities`
声明，门面据此决定是否降级。
"""

from service.capture.backends.base import CaptureBackend
from service.capture.backends.dxgi import DxgiDesktopBackend
from service.capture.backends.gdi import GdiScreenBackend, GdiWindowBackend
from service.capture.backends.wgc import WgcWindowBackend

__all__ = [
    "CaptureBackend",
    "DxgiDesktopBackend",
    "GdiScreenBackend",
    "GdiWindowBackend",
    "WgcWindowBackend",
]
