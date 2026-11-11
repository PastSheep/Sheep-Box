"""抓取后端的统一契约。

所有后端（GDI 屏幕/窗口、DXGI、WGC）都实现同一份协议：打开一次、按区域抓帧、
关闭。能力差异用 :class:`~service.capture.models.BackendCapabilities` 声明，
由门面层或其他后端决定是否降级，而不是硬编码在消费方。
"""

from __future__ import annotations

from typing import Protocol

from service.capture.models import (
    BackendCapabilities,
    CaptureRegion,
    ScreenFrame,
    WindowInfo,
)

__all__ = ["CaptureBackend"]


class CaptureBackend(Protocol):
    """一次抓取会话的后端接口。"""

    @property
    def name(self) -> str:
        """后端标识，写进 ``ScreenFrame.backend``。"""
        ...

    @property
    def capabilities(self) -> BackendCapabilities:
        """能力声明。"""
        ...

    def open(self, window: WindowInfo) -> None:
        """绑定目标窗口并完成必要的初始化。

        Args:
            window: 目标窗口信息。
        """
        ...

    def capture(self, region: CaptureRegion, *, space: str) -> ScreenFrame:
        """抓取一帧。

        Args:
            region: 客户区口径的区域。
            space: 期望输出的像素口径，``client`` 或 ``screen``。

        Returns:
            抓取结果。
        """
        ...

    def close(self) -> None:
        """释放资源；重复调用安全。"""
        ...
