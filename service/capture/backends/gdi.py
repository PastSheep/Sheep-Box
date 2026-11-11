"""GDI 抓取后端。

两条路径共用一套 DIB 与位块传输代码，区别只在源 DC 与偏移：

- :class:`GdiScreenBackend`：``GetDC(NULL)`` 抓屏幕帧，按客户区在屏幕上的位置
  裁剪。所见即所得，但被遮挡区域截到的是遮挡者的内容；
- :class:`GdiWindowBackend`：``GetDC(hwnd)`` 抓窗口自身表面，部分遮挡时仍能拿到
  内容，但硬件合成窗口（浏览器、Electron、多数 D3D 游戏）常返回全黑。
"""

from __future__ import annotations

import time

from common.exceptions import CaptureBackendError, CaptureRegionError
from service.capture import _win32, windows
from service.capture.models import (
    SPACE_CLIENT,
    SPACE_SCREEN,
    BackendCapabilities,
    CaptureRegion,
    ScreenFrame,
    WindowInfo,
)

__all__ = ["GdiScreenBackend", "GdiWindowBackend", "crop_rows"]


def crop_rows(
    data: bytes,
    source_width: int,
    region: CaptureRegion,
) -> bytes:
    """从整窗 BGRA 缓冲中裁出子区域。

    用于 ``PrintWindow``：该 API 只能整窗输出，子区域需要在内存里再裁一次。

    Args:
        data: 整窗像素，``stride == source_width * 4``。
        source_width: 整窗宽。
        region: 要裁出的区域（已钳制）。

    Returns:
        子区域像素。

    Raises:
        CaptureRegionError: 区域为空或超出源图。
    """
    if region.empty:
        raise CaptureRegionError("裁剪区域为空")
    if region.x + region.width > source_width:
        raise CaptureRegionError("裁剪区域超出源图宽度")

    source_stride = source_width * 4
    row_bytes = region.width * 4
    output = bytearray(row_bytes * region.height)
    for index in range(region.height):
        src_offset = (region.y + index) * source_stride + region.x * 4
        dst_offset = index * row_bytes
        output[dst_offset : dst_offset + row_bytes] = data[
            src_offset : src_offset + row_bytes
        ]
    return bytes(output)


class _GdiBase:
    """共用的表面管理与释放逻辑。"""

    name: str

    def __init__(self) -> None:
        self._window: WindowInfo | None = None
        self._surface: _win32.DibSurface | None = None
        self._surface_size: tuple[int, int] = (0, 0)

    def open(self, window: WindowInfo) -> None:
        """绑定目标窗口。

        Args:
            window: 目标窗口信息。
        """
        self._window = window

    def close(self) -> None:
        """释放 DIB 表面与 DC。"""
        if self._surface is not None:
            self._surface.close()
            self._surface = None
            self._surface_size = (0, 0)

    def _require_window(self) -> WindowInfo:
        """返回已绑定的窗口。

        Raises:
            CaptureBackendError: 尚未 ``open``。
        """
        if self._window is None:
            raise CaptureBackendError(f"{self.name} 尚未 open()")
        return self._window

    def _surface_for(self, width: int, height: int) -> _win32.DibSurface:
        """取得（必要时重建）指定尺寸的 DIB 表面。

        Args:
            width: 宽。
            height: 高。

        Returns:
            可写入的表面。
        """
        if self._surface is not None and self._surface_size == (width, height):
            return self._surface
        self.close()
        self._surface = _win32.make_surface(width, height)
        self._surface_size = (width, height)
        return self._surface


class GdiScreenBackend(_GdiBase):
    """屏幕帧后端：所见即所得，要求窗口在屏幕上且未被遮挡。"""

    name = "screen"

    @property
    def capabilities(self) -> BackendCapabilities:
        """能力声明。"""
        return BackendCapabilities(
            name=self.name,
            continuous=False,
            occluded_ok=False,
            notes="屏幕帧口径；被遮挡区域截到的是遮挡者内容，需前置校验",
        )

    def capture(self, region: CaptureRegion, *, space: str) -> ScreenFrame:
        """抓取一帧屏幕像素。

        Args:
            region: 客户区口径区域。
            space: 忽略（屏幕后端始终输出屏幕物理像素）。

        Returns:
            抓取结果，``space == "screen"``。

        Raises:
            CaptureRegionError: 区域为空或换算后尺寸非正。
            CaptureBackendError: 获取 DC 或位块传输失败。
        """
        window = self._require_window()
        left, top, width, height = windows.client_to_screen_rect(window, region)
        if width <= 0 or height <= 0:
            raise CaptureRegionError(
                f"区域 {region} 换算到屏幕后尺寸非法：{width}x{height}"
            )
        surface = self._surface_for(width, height)
        try:
            source_dc = _win32.get_dc(0)
            try:
                _win32.bitblt(surface.dc, source_dc, left, top, width, height)
            finally:
                _win32.release_dc(0, source_dc)
        except _win32.NativeApiError as exc:
            raise CaptureBackendError(f"{self.name} 抓取失败：{exc}") from exc
        data = surface.read()
        return ScreenFrame(
            width=width,
            height=height,
            data=data,
            region=region,
            space=SPACE_SCREEN,
            backend=self.name,
            window=window,
            timestamp=time.time(),
        )


class GdiWindowBackend(_GdiBase):
    """窗口表面后端：快，对合成窗口可能全黑。"""

    name = "gdi-window"

    @property
    def capabilities(self) -> BackendCapabilities:
        """能力声明。"""
        return BackendCapabilities(
            name=self.name,
            continuous=False,
            occluded_ok=True,
            notes="窗口自身表面；硬件合成窗口常返回全黑，判黑后应退屏幕",
        )

    def capture(self, region: CaptureRegion, *, space: str) -> ScreenFrame:
        """抓取一帧窗口表面像素。

        Args:
            region: 客户区口径区域。
            space: 必须为 ``client``。

        Returns:
            抓取结果，``space == "client"``。

        Raises:
            ValueError: ``space`` 不是 ``client``。
            CaptureRegionError: 区域为空。
            CaptureBackendError: 获取 DC 或位块传输失败。
        """
        if space != SPACE_CLIENT:
            raise ValueError(f"{self.name} 只输出 client 口径，收到 {space!r}")
        window = self._require_window()
        if region.empty:
            raise CaptureRegionError("区域为空")
        surface = self._surface_for(region.width, region.height)
        try:
            source_dc = _win32.get_dc(window.hwnd)
            try:
                _win32.bitblt(
                    surface.dc,
                    source_dc,
                    region.x,
                    region.y,
                    region.width,
                    region.height,
                )
            finally:
                _win32.release_dc(window.hwnd, source_dc)
        except _win32.NativeApiError as exc:
            raise CaptureBackendError(f"{self.name} 抓取失败：{exc}") from exc
        data = surface.read()
        return ScreenFrame(
            width=region.width,
            height=region.height,
            data=data,
            region=region,
            space=SPACE_CLIENT,
            backend=self.name,
            window=window,
            timestamp=time.time(),
        )

    def capture_print_window(self, region: CaptureRegion) -> ScreenFrame:
        """用 ``PrintWindow`` 画整窗再裁出区域。

        对老式 GDI 程序往往能拿到完整内容；对 D3D/合成窗口通常仍是黑图，是否
        采用由门面层根据判黑结果决定。

        Args:
            region: 客户区口径区域。

        Returns:
            抓取结果，``space == "client"``。

        Raises:
            CaptureBackendError: ``PrintWindow`` 失败或窗口尺寸非法。
        """
        window = self._require_window()
        if window.client_width <= 0 or window.client_height <= 0:
            raise CaptureBackendError("窗口客户区尺寸为 0，无法 PrintWindow")
        full = region.clamp(window.client_width, window.client_height)
        if full.empty:
            raise CaptureRegionError("区域为空")
        surface = self._surface_for(window.client_width, window.client_height)
        if not _win32.print_window(window.hwnd, surface.dc):
            raise CaptureBackendError("PrintWindow 返回失败", _win32.last_error())
        data = crop_rows(surface.read(), window.client_width, full)
        return ScreenFrame(
            width=full.width,
            height=full.height,
            data=data,
            region=full,
            space=SPACE_CLIENT,
            backend="printwindow",
            window=window,
            timestamp=time.time(),
        )
