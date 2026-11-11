"""DXGI 桌面复制后端。

与 :class:`~service.capture.backends.gdi.GdiScreenBackend` 取同样的「屏幕内容」，
区别在于数据来自 DWM 的组合结果、连续拉帧不必每次重建上下文，因此抗撕裂、单帧
开销更低。它仍然是所见即所得的口径：目标窗口被别的窗口盖住时，截到的是遮挡者。

坐标换算链路：客户区区域 → 屏幕物理矩形 → 减去所在输出的左上角 → 输出本地区域。
窗口移动只改变前三步的结果，复制接口本身不用重建，所以「位置变化、比例固定」的
游戏窗口天然适配。
"""

from __future__ import annotations

import logging
import time

from common.exceptions import CaptureBackendError, CaptureRegionError
from service.capture import windows
from service.capture.backends._dxgi_native import (
    AccessLostError,
    DuplicationSession,
    virtual_contains,
)
from service.capture.models import (
    SPACE_SCREEN,
    BackendCapabilities,
    CaptureRegion,
    ScreenFrame,
    WindowInfo,
)

__all__ = ["DxgiDesktopBackend"]

logger = logging.getLogger(__name__)


class DxgiDesktopBackend:
    """桌面复制后端：单个输出、屏幕口径、可连续拉帧。"""

    name = "dxgi"

    def __init__(self, *, timeout_ms: int = 0) -> None:
        """初始化。

        Args:
            timeout_ms: 等待新帧的毫秒数；0 表示只取已在队列里的帧。
        """
        self._window: WindowInfo | None = None
        self._session: DuplicationSession | None = None
        self._timeout_ms = max(timeout_ms, 0)

    @property
    def capabilities(self) -> BackendCapabilities:
        """能力声明。"""
        return BackendCapabilities(
            name=self.name,
            continuous=True,
            occluded_ok=False,
            notes="桌面复制整屏像素；被遮挡截到遮挡者内容，需前置校验；Windows 8+",
        )

    def open(self, window: WindowInfo) -> None:
        """绑定目标窗口；复制会话在首次抓取时按区域所在显示器建立。

        Args:
            window: 目标窗口信息。
        """
        self._window = window

    def close(self) -> None:
        """释放复制会话；重复调用安全。"""
        if self._session is not None:
            self._session.close()
            self._session = None

    def capture(self, region: CaptureRegion, *, space: str) -> ScreenFrame:
        """抓取一帧。

        Args:
            region: 客户区口径区域。
            space: 忽略；桌面复制始终输出屏幕物理像素。

        Returns:
            抓取结果，``space == "screen"``。

        Raises:
            CaptureRegionError: 区域为空或换算后尺寸非法。
            CaptureUnavailableError: DXGI 不可用、区域跨显示器或当前模式不支持。
            CaptureBackendError: 抓取或读回失败。
        """
        window = self._require_window()
        if region.empty:
            raise CaptureRegionError("区域为空")
        rect = windows.client_to_screen_rect(window, region)
        if rect[2] <= 0 or rect[3] <= 0:
            raise CaptureRegionError(
                f"区域 {region} 换算到屏幕后尺寸非法：{rect[2]}x{rect[3]}"
            )
        data = self._grab_with_recovery(rect)
        return ScreenFrame(
            # 屏幕口径下 ``ScreenFrame`` 的宽高是**输出像素**，必须用换算后的矩形；
            # 用 ``region.width`` 在 DPI 虚拟化窗口（1280×720 → 1600×900）下会与
            # 缓冲长度不符，硬校验直接抛 ValueError。
            width=rect[2],
            height=rect[3],
            data=data,
            region=region,
            space=SPACE_SCREEN,
            backend=self.name,
            window=window,
            timestamp=time.time(),
        )

    def _require_window(self) -> WindowInfo:
        """返回已绑定的窗口。

        Raises:
            CaptureBackendError: 尚未 ``open``。
        """
        if self._window is None:
            raise CaptureBackendError(f"{self.name} 尚未 open()")
        return self._window

    def _grab_with_recovery(self, rect: tuple[int, int, int, int]) -> bytes:
        """抓取屏幕矩形，桌面复制失效时重建一次。

        Args:
            rect: 屏幕物理矩形 ``(left, top, width, height)``。

        Returns:
            区域像素。

        Raises:
            CaptureBackendError: 重建后仍失败。
        """
        session = self._ensure_session(self._center(rect))
        try:
            return session.grab(self._local_region(rect, session), self._timeout_ms)
        except AccessLostError:
            logger.debug("桌面复制失效，按同一屏幕位置重建一次")
        session.close()
        session = self._ensure_session(self._center(rect))
        try:
            return session.grab(self._local_region(rect, session), self._timeout_ms)
        except AccessLostError as exc:
            raise CaptureBackendError(
                "桌面复制重建后仍然失效（可能正在切换分辨率或全屏）"
            ) from exc

    def _ensure_session(self, point: tuple[int, int]) -> DuplicationSession:
        """取得覆盖目标点的复制会话，必要时按该点重建。

        Args:
            point: 屏幕物理坐标。

        Returns:
            已打开的会话。

        Raises:
            CaptureUnavailableError: 该点没有可用输出或不支持桌面复制。
        """
        if self._session is not None:
            output_rect = self._session.output_rect
            if self._session.opened and virtual_contains(output_rect, point):
                return self._session
            self._session.close()
        session = DuplicationSession()
        session.open(point)
        self._session = session
        return session

    @staticmethod
    def _center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
        """取屏幕矩形中心点，用于判定落在哪个输出。"""
        left, top, width, height = rect
        return left + width // 2, top + height // 2

    @staticmethod
    def _local_region(
        rect: tuple[int, int, int, int], session: DuplicationSession
    ) -> tuple[int, int, int, int]:
        """把屏幕矩形换算成当前输出的本地区域。"""
        output_left, output_top, _, _ = session.output_rect
        return rect[0] - output_left, rect[1] - output_top, rect[2], rect[3]
