"""WGC（Windows Graphics Capture）单窗口后端。

与 GDI / DXGI 抓「屏幕内容」不同，WGC 抓的是**目标窗口自己的合成表面**：被别的
窗口盖住、窗口不在最前面，都能拿到窗口内容，且帧尺寸随窗口变化自动更新。代价是
需要 Windows 10 1903+、支持该 API 的显卡驱动，并依赖第三方包 ``windows-capture``。

实现要点：

- 帧是**整窗口径**（含标题栏与边框，尺寸等于 ``WindowInfo.frame_rect``），客户区
  在帧内的偏移由 ``client_origin - frame_rect`` 算出，抓取时按该偏移裁剪；
- 捕获在独立线程里连续跑。回调默认不拷贝像素，只有业务发起抓取时才拷贝一帧，
  避免 1 秒抓一次却每秒拷贝 60 帧；
- 画面静止时 WGC 不产生新帧，抓取会先短暂等待新帧，超时则用缓存帧，语义与
  :class:`~service.capture.backends.dxgi.DxgiDesktopBackend` 一致；
- Windows 10 不支持 ``IsBorderRequired``（也就是 ``draw_border`` 开关）与
  ``minimum_update_interval``，传入会让会话直接抛异常，因此这里都不传；回调频率
  交给系统，节流靠「只在业务请求时拷贝」实现（Win10 无捕获边框，Win11 会画一圈
  黄框，后者是该 API 的既定行为）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np

from common.exceptions import (
    CaptureBackendError,
    CaptureRegionError,
    CaptureUnavailableError,
)
from service.capture.models import (
    SPACE_CLIENT,
    BackendCapabilities,
    CaptureRegion,
    ScreenFrame,
    WindowInfo,
)

__all__ = ["WgcWindowBackend"]

logger = logging.getLogger(__name__)


def _capture_class() -> Any:
    """延迟导入 ``windows-capture``。

    Returns:
        ``WindowsCapture`` 类。

    Raises:
        CaptureUnavailableError: 未安装该包。
    """
    try:
        from windows_capture import WindowsCapture
    except ImportError as exc:  # pragma: no cover - 只有缺依赖时才走到
        raise CaptureUnavailableError(
            "未安装 windows-capture，WGC 后端不可用（pip install windows-capture）"
        ) from exc
    return WindowsCapture


class WgcWindowBackend:
    """单窗口捕获后端：抓窗口自身内容，不受遮挡影响。"""

    name = "wgc"

    def __init__(
        self,
        *,
        fresh_timeout_ms: int = 50,
        startup_timeout_ms: int = 800,
    ) -> None:
        """初始化。

        Args:
            fresh_timeout_ms: 抓取时等待新帧的时间；超时用缓存帧。
            startup_timeout_ms: 会话启动后等待首帧的超时，超过视为不可用。
        """
        self._fresh_timeout_ms = max(0, fresh_timeout_ms)
        self._startup_timeout_ms = max(1, startup_timeout_ms)
        self._window: WindowInfo | None = None
        self._hwnd: int | None = None
        self._capture: Any = None
        self._control: Any = None
        self._latest: tuple[int, int, np.ndarray] | None = None
        self._want = False
        self._new_frame = threading.Event()
        self._closed = threading.Event()

    @property
    def capabilities(self) -> BackendCapabilities:
        """能力声明。"""
        return BackendCapabilities(
            name=self.name,
            continuous=True,
            occluded_ok=True,
            needs_external_dep=True,
            notes=(
                "单窗口捕获；被遮挡仍拿到窗口内容；"
                "需要 windows-capture 包与 Win10 1903+"
            ),
        )

    def open(self, window: WindowInfo) -> None:
        """绑定窗口；同一句柄重复调用只刷新尺寸快照，不重建会话。

        Args:
            window: 目标窗口信息。

        Raises:
            CaptureUnavailableError: 未安装依赖或会话启动失败。
            CaptureBackendError: 启动后没有在超时内产生首帧。
        """
        if self._hwnd == window.hwnd and self._control is not None:
            self._window = window
            return
        self.close()
        self._window = window
        self._start(window)

    def close(self) -> None:
        """停止捕获线程并释放会话；重复调用安全。"""
        control = self._control
        self._control = None
        self._capture = None
        self._hwnd = None
        self._latest = None
        self._want = False
        self._new_frame.clear()
        if control is None:
            return
        try:
            control.stop()
        except Exception:
            logger.debug("停止 WGC 会话时抛异常（已忽略）", exc_info=True)
        try:
            control.wait()
        except Exception:
            logger.debug("等待 WGC 会话结束时抛异常（已忽略）", exc_info=True)
        self._closed.clear()

    def capture(self, region: CaptureRegion, *, space: str) -> ScreenFrame:
        """按客户区区域裁剪一帧。

        Args:
            region: 客户区口径区域。
            space: 必须为 ``client``（WGC 输出窗口内容，不是屏幕像素）。

        Returns:
            抓取结果，``space == "client"``。

        Raises:
            ValueError: ``space`` 不是 ``client``。
            CaptureRegionError: 区域为空，或换算到帧内后越界。
            CaptureBackendError: 会话已结束或没有可用帧。
        """
        if space != SPACE_CLIENT:
            raise ValueError(f"{self.name} 只输出 client 口径，收到 {space!r}")
        window = self._require_window()
        if region.empty:
            raise CaptureRegionError("区域为空")
        self._ensure_alive()

        frame_width, frame_height, buffer = self._take_frame()
        offset_x = window.client_origin[0] - window.frame_rect[0]
        offset_y = window.client_origin[1] - window.frame_rect[1]
        left = offset_x + region.x
        top = offset_y + region.y
        if (
            left < 0
            or top < 0
            or left + region.width > frame_width
            or top + region.height > frame_height
        ):
            raise CaptureRegionError(
                f"区域 {region} 换算到 WGC 帧 {frame_width}x{frame_height} 后越界"
                f"（客户区偏移 {offset_x},{offset_y}）"
            )

        data = buffer[
            top : top + region.height, left : left + region.width, :
        ].tobytes()
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

    def on_frame_arrived(self, frame: Any, _control: Any) -> None:
        """捕获线程回调：只有业务在等帧时才拷贝像素。

        Args:
            frame: ``windows-capture`` 的 ``Frame``（``frame_buffer`` 为 BGRA 视图）。
            _control: 内部停止控制对象（本后端不使用）。
        """
        if not self._want:
            return
        try:
            buffer = np.asarray(frame.frame_buffer).copy()
        except (AttributeError, ValueError) as exc:
            logger.debug("WGC 帧缓冲不可用：%s", exc)
            return
        self._latest = (int(frame.width), int(frame.height), buffer)
        self._want = False
        self._new_frame.set()

    def on_closed(self) -> None:
        """捕获线程回调：目标窗口关闭或会话终止。"""
        self._closed.set()
        self._new_frame.set()

    def _start(self, window: WindowInfo) -> None:
        """创建会话并启动捕获线程。

        Args:
            window: 目标窗口信息。

        Raises:
            CaptureUnavailableError: 依赖缺失或启动失败。
            CaptureBackendError: 启动后没有在超时内产生首帧。
        """
        capture_cls = _capture_class()
        self._closed.clear()
        self._new_frame.clear()
        self._latest = None
        capture = capture_cls(
            cursor_capture=False,
            window_hwnd=window.hwnd,
        )
        capture.event(self.on_frame_arrived)
        capture.event(self.on_closed)
        self._want = True
        try:
            control = capture.start_free_threaded()
        except Exception as exc:
            raise CaptureUnavailableError(f"WGC 启动失败：{exc}") from exc
        self._capture = capture
        self._control = control
        self._hwnd = window.hwnd
        if not self._new_frame.wait(self._startup_timeout_ms / 1000):
            self.close()
            raise CaptureBackendError(
                "WGC 启动后在超时内没有产生首帧（窗口可能不可见）"
            )

    def _take_frame(self) -> tuple[int, int, np.ndarray]:
        """取一帧：先短暂等待新帧，超时回落到缓存帧。

        Returns:
            ``(宽, 高, BGRA 数组)``，数组为 ``(高, 宽, 4)``。

        Raises:
            CaptureBackendError: 既没有新帧也没有缓存。
        """
        cached = self._latest
        if self._fresh_timeout_ms > 0:
            self._want = True
            self._new_frame.clear()
            if self._new_frame.wait(self._fresh_timeout_ms / 1000):
                latest = self._latest
                if latest is not None:
                    return latest
            self._want = False
        if cached is not None:
            return cached
        raise CaptureBackendError("WGC 暂无可用帧（会话可能已结束）")

    def _ensure_alive(self) -> None:
        """确认会话仍在运行。

        Raises:
            CaptureBackendError: 窗口已关闭或会话已结束。
        """
        if self._closed.is_set():
            raise CaptureBackendError("目标窗口已关闭，WGC 会话结束")
        if self._control is None:
            raise CaptureBackendError("WGC 会话未启动")
        if self._control.is_finished():
            raise CaptureBackendError("WGC 会话已结束")

    def _require_window(self) -> WindowInfo:
        """返回已绑定的窗口。

        Raises:
            CaptureBackendError: 尚未 ``open``。
        """
        if self._window is None:
            raise CaptureBackendError(f"{self.name} 尚未 open()")
        return self._window
