"""截图门面：校验窗口与区域、选择后端、在失败时降级。

对外的唯一入口是 :class:`WindowCapturer`。它只依赖后端协议，因此将来加入 DXGI
或 WGC 后端时调用方无需改动。
"""

from __future__ import annotations

import logging
from dataclasses import replace

from common.exceptions import (
    CaptureBackendError,
    CaptureOccludedError,
    CaptureRegionError,
    CaptureUnavailableError,
    WindowNotVisibleError,
    WindowOutOfScreenError,
)
from service.capture import _win32, windows
from service.capture.backends.dxgi import DxgiDesktopBackend
from service.capture.backends.gdi import GdiScreenBackend, GdiWindowBackend
from service.capture.backends.wgc import WgcWindowBackend
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

__all__ = ["WindowCapturer"]

logger = logging.getLogger(__name__)

# 判黑阈值：暗像素（或暗色单色）占比超过该值即视为窗口表面无内容
_BLANK_THRESHOLD = 0.995

_IMPLEMENTED_BACKENDS = frozenset({"screen", "window", "dxgi", "wgc"})


def _is_blank(data: bytes) -> bool:
    """判断一帧是否可视为「无内容」。

    Args:
        data: BGRA 像素。

    Returns:
        暗像素或近黑单色占比是否达到阈值。
    """
    return blank_ratio(data) >= _BLANK_THRESHOLD


def _intersects_screen(window: WindowInfo) -> bool:
    """判断窗口的**客户区**是否与虚拟桌面有交集。

    用客户区而不是 ``frame_rect``：窗口被拖到只剩标题栏时，边框仍与桌面相交，
    但客户区已经完全在屏幕外——那种情况必须报 ``WindowOutOfScreenError``，
    否则屏幕后端会 BitBlt 一个完全越界的源矩形，返回未写入的旧缓冲内容。

    Args:
        window: 目标窗口。

    Returns:
        有交集为真。
    """
    left, top = window.client_origin
    width, height = window.screen_width, window.screen_height
    if width <= 0 or height <= 0:
        return False
    screen_left, screen_top, screen_width, screen_height = _win32.virtual_screen_rect()
    return not (
        left + width <= screen_left
        or top + height <= screen_top
        or left >= screen_left + screen_width
        or top >= screen_top + screen_height
    )


class WindowCapturer:
    """窗口区域截图门面。

    使用方式::

        with WindowCapturer() as capturer:
            frame = capturer.capture(hwnd, CaptureRegion(0, 0, 800, 600))

    连续抓取时复用同一个实例，可命中 DIB 缓冲缓存。
    """

    def __init__(self, options: CaptureOptions | None = None) -> None:
        self._options = options or CaptureOptions()
        self._window_backend = GdiWindowBackend()
        self._screen_backend = GdiScreenBackend()
        self._dxgi_backend = DxgiDesktopBackend()
        self._wgc_backend = WgcWindowBackend()

    def __enter__(self) -> WindowCapturer:
        """支持 ``with`` 用法。"""
        return self

    def __exit__(self, *_exc: object) -> None:
        """退出时释放资源。"""
        self.close()

    @property
    def options(self) -> CaptureOptions:
        """构造时指定的默认策略。"""
        return self._options

    def close(self) -> None:
        """释放后端持有的 DC、DIB、复制会话与捕获线程。"""
        self._window_backend.close()
        self._screen_backend.close()
        self._dxgi_backend.close()
        self._wgc_backend.close()

    def capture(
        self,
        hwnd: int,
        region: CaptureRegion | NormalizedRegion,
        *,
        options: CaptureOptions | None = None,
    ) -> ScreenFrame:
        """抓取指定窗口的一块区域。

        Args:
            hwnd: 目标窗口句柄。
            region: 客户区口径的像素区域，或按比例描述的区域。
            options: 覆盖本次抓取的策略；省略时用构造参数。

        Returns:
            抓取结果。``space`` 为 ``client``（窗口表面像素）或 ``screen``
            （屏幕物理像素），以实际产出为准。

        Raises:
            WindowNotVisibleError: 窗口不可见或已最小化。
            WindowOutOfScreenError: 窗口与虚拟桌面无交集。
            CaptureRegionError: 区域为空或越界且未允许钳制。
            CaptureOccludedError: 屏幕口径下区域被其它窗口覆盖。
            CaptureUnavailableError: 请求的后端不可用或环境不满足。
            CaptureBackendError: 抓取调用失败。
        """
        opts = options or self._options
        if opts.include_frame:
            raise CaptureUnavailableError("include_frame 尚未实现，当前只支持客户区")

        window = windows.get_window_info(hwnd)
        if not window.capturable:
            raise WindowNotVisibleError(f"窗口不可见或已最小化：{hwnd}")
        if not _intersects_screen(window):
            raise WindowOutOfScreenError(f"窗口不在任何显示器上：{hwnd}")

        target = self._resolve_region(window, region, opts)
        backend = self._resolve_backend(opts)

        if backend == "screen":
            return self._capture_screen(window, target, opts, degraded=False)
        if backend == "dxgi":
            return self._capture_dxgi(window, target, opts, degraded=False)
        if backend == "wgc":
            return self._capture_wgc(window, target, opts, degraded=False)

        frame = self._try_window(window, target, opts)
        if frame is not None:
            return frame
        logger.debug("窗口表面无内容：hwnd=%s", hwnd)
        frame = self._try_dxgi(window, target, opts)
        if frame is not None:
            return frame
        logger.debug("桌面复制不可用，降级到 GDI 屏幕帧：hwnd=%s", hwnd)
        return self._capture_screen(window, target, opts, degraded=True)

    def _resolve_backend(self, opts: CaptureOptions) -> str:
        """把 ``backend`` 策略解析成具体实现。

        Args:
            opts: 本次策略。

        Returns:
            ``"screen"``、``"window"``、``"dxgi"`` 或 ``"wgc"``。

        Raises:
            CaptureUnavailableError: 请求的后端不存在。
        """
        if opts.backend not in _IMPLEMENTED_BACKENDS and opts.backend != "auto":
            raise CaptureUnavailableError(f"未知后端：{opts.backend!r}")
        if opts.backend != "auto":
            return opts.backend
        if opts.prefer_screen or opts.space == SPACE_SCREEN:
            return "screen"
        return "window"

    def _resolve_region(
        self,
        window: WindowInfo,
        region: CaptureRegion | NormalizedRegion,
        opts: CaptureOptions,
    ) -> CaptureRegion:
        """把输入区域统一成钳制后的客户区像素区域。

        Args:
            window: 目标窗口。
            region: 像素或比例区域。
            opts: 本次策略。

        Returns:
            客户区口径的区域。

        Raises:
            CaptureRegionError: 区域为空、越界且不允许钳制，或尺寸非法。
        """
        if isinstance(region, NormalizedRegion):
            if opts.space == SPACE_SCREEN:
                base_width, base_height = window.screen_width, window.screen_height
            else:
                base_width, base_height = window.client_width, window.client_height
            raw = region.to_pixels(base_width, base_height)
        else:
            raw = region

        if not opts.clamp_region:
            if (
                raw.x < 0
                or raw.y < 0
                or raw.x + raw.width > window.client_width
                or raw.y + raw.height > window.client_height
            ):
                raise CaptureRegionError(f"区域越界：{raw}")
            clamped = raw
        else:
            clamped = raw.clamp(window.client_width, window.client_height)

        if clamped.empty:
            raise CaptureRegionError(
                f"区域 {raw} 完全落在客户区 "
                f"{window.client_width}x{window.client_height} 之外"
            )
        return clamped

    def _try_window(
        self,
        window: WindowInfo,
        region: CaptureRegion,
        opts: CaptureOptions,
    ) -> ScreenFrame | None:
        """尝试窗口表面通道，内容为空时返回 ``None``。

        Args:
            window: 目标窗口。
            region: 已钳制的客户区区域。
            opts: 本次策略；``detect_blank`` 为假时不做判黑与回退。

        Returns:
            可用帧；判黑或调用失败时为 ``None``。
        """
        self._window_backend.open(window)
        try:
            frame = self._window_backend.capture(region, space=SPACE_CLIENT)
        except CaptureBackendError as exc:
            logger.debug("窗口表面抓取失败：%s", exc)
            return None
        if not opts.detect_blank or not _is_blank(frame.data):
            return frame

        try:
            print_frame = self._window_backend.capture_print_window(region)
        except CaptureBackendError as exc:
            logger.debug("PrintWindow 失败：%s", exc)
            return None
        if not _is_blank(print_frame.data):
            return print_frame
        return None

    def _capture_dxgi(
        self,
        window: WindowInfo,
        region: CaptureRegion,
        opts: CaptureOptions,
        *,
        degraded: bool,
    ) -> ScreenFrame:
        """用桌面复制抓一帧，必要时先做遮挡校验。

        Args:
            window: 目标窗口。
            region: 客户区口径区域。
            opts: 本次策略。
            degraded: 是否由降级产生。

        Returns:
            屏幕口径的帧。

        Raises:
            CaptureOccludedError: 区域被其它窗口覆盖。
            CaptureUnavailableError: DXGI 不可用或区域跨显示器。
            CaptureBackendError: 抓取失败。
        """
        if opts.verify_occlusion and windows.is_occluded(
            window, region, strict=opts.strict_foreground
        ):
            raise CaptureOccludedError("目标区域被其它窗口覆盖，抓取会得到遮挡者的内容")
        self._dxgi_backend.open(window)
        frame = self._dxgi_backend.capture(region, space=SPACE_SCREEN)
        if not opts.verify_occlusion:
            # 关掉校验不等于「确认没被遮挡」，只是把判断权交给业务：标记为可能
            # 含遮挡者内容，业务据此决定要不要用。
            frame = replace(frame, occluded=True)
        if degraded:
            frame = replace(frame, degraded=True)
        return frame

    def _try_dxgi(
        self,
        window: WindowInfo,
        region: CaptureRegion,
        opts: CaptureOptions,
    ) -> ScreenFrame | None:
        """尝试桌面复制，不可用时返回 ``None``。

        Args:
            window: 目标窗口。
            region: 客户区口径区域。
            opts: 本次策略。

        Returns:
            降级标记为真的帧；环境不支持或失败时为 ``None``。
        """
        try:
            return self._capture_dxgi(window, region, opts, degraded=True)
        except CaptureOccludedError:
            return None
        except (CaptureUnavailableError, CaptureBackendError) as exc:
            logger.debug("桌面复制不可用：%s", exc)
            return None

    def _capture_wgc(
        self,
        window: WindowInfo,
        region: CaptureRegion,
        opts: CaptureOptions,
        *,
        degraded: bool,
    ) -> ScreenFrame:
        """用单窗口捕获抓一帧。

        WGC 拿的是窗口自身的合成表面，被别的窗口盖住也照样是目标窗口的内容，
        因此不做遮挡校验（``verify_occlusion`` 对它没有意义）。

        Args:
            window: 目标窗口。
            region: 客户区口径区域。
            opts: 本次策略。
            degraded: 是否由降级产生。

        Returns:
            客户区口径的帧。

        Raises:
            CaptureUnavailableError: 依赖缺失或环境不支持。
            CaptureBackendError: 抓取失败。
        """
        self._wgc_backend.open(window)
        frame = self._wgc_backend.capture(region, space=SPACE_CLIENT)
        if degraded:
            frame = replace(frame, degraded=True)
        return frame

    def _capture_screen(
        self,
        window: WindowInfo,
        region: CaptureRegion,
        opts: CaptureOptions,
        *,
        degraded: bool,
    ) -> ScreenFrame:
        """抓取屏幕帧，必要时先做遮挡校验。

        Args:
            window: 目标窗口。
            region: 客户区口径区域。
            opts: 本次策略。
            degraded: 是否由降级产生。

        Returns:
            屏幕口径的帧。

        Raises:
            CaptureOccludedError: 区域被其它窗口覆盖。
        """
        if opts.verify_occlusion and windows.is_occluded(
            window, region, strict=opts.strict_foreground
        ):
            raise CaptureOccludedError("目标区域被其它窗口覆盖，抓取会得到遮挡者的内容")
        self._screen_backend.open(window)
        frame = self._screen_backend.capture(region, space=SPACE_SCREEN)
        if not opts.verify_occlusion:
            frame = replace(frame, occluded=True)
        if degraded:
            frame = replace(frame, degraded=True)
        if _is_blank(frame.data):
            logger.debug("屏幕帧同样无内容：hwnd=%s", window.hwnd)
        return frame
