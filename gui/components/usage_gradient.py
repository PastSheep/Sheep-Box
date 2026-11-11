"""利用率 → 颜色的渐变求值与缓存。

锚点由配置提供（``app.status_bar.gradient_stops``），数量不限、位置不重复。
求值按 5% 粒度缓存：状态栏每秒刷新三项指标，若每帧都做浮点插值，颜色值会
在相邻百分点间来回抖动，观感上像在闪烁；量化到 5 个点一档后，展示稳定，
计算量也从「每帧若干次插值」降到「每档一次」，最多 21 个缓存项。

设置页的轨道预览与状态栏的压力点共用同一份锚点，改配置即同时生效。
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QLinearGradient

__all__ = ["UsageGradient"]

#: 缓存粒度（百分比）：0 / 5 / ... / 100 共 21 档
CACHE_STEP = 5.0


class UsageGradient:
    """由若干颜色锚点构成的线性渐变。

    Args:
        stops: ``[(位置百分比, #RRGGBB), ...]``，位置范围 0~100。

    Raises:
        ValueError: 锚点为空（无法求值）。
    """

    def __init__(self, stops: Sequence[tuple[float, str]]) -> None:
        if not stops:
            raise ValueError("至少需要一个渐变锚点")
        self._stops: tuple[tuple[float, QColor], ...] = tuple(
            sorted(
                ((float(at), QColor(color)) for at, color in stops),
                key=lambda stop: stop[0],
            )
        )
        self._cache: dict[int, QColor] = {}

    def stops(self) -> tuple[tuple[float, QColor], ...]:
        """按位置升序返回锚点（位置, 颜色）。"""
        return self._stops

    def color_at(self, percent: float) -> QColor:
        """取指定利用率对应的颜色（按 5% 粒度量化后命中缓存）。

        Args:
            percent: 利用率百分比，越界会自动钳制到 0~100。

        Returns:
            颜色副本，调用方修改不影响缓存。
        """
        clamped = max(0.0, min(100.0, float(percent)))
        bucket = round(clamped / CACHE_STEP) * int(CACHE_STEP)
        bucket = max(0, min(100, bucket))
        cached = self._cache.get(bucket)
        if cached is None:
            cached = self._sample(float(bucket))
            self._cache[bucket] = cached
        return QColor(cached)

    def cached_levels(self) -> int:
        """已缓存的色阶数量（供测试断言缓存行为）。"""
        return len(self._cache)

    def linear_gradient(self, start: QPointF, end: QPointF) -> QLinearGradient:
        """按锚点构造 Qt 线性渐变，用于绘制轨道。

        Args:
            start: 渐变起点（对应 0%）。
            end: 渐变终点（对应 100%）。

        Returns:
            可直接传给 ``QPainter.fillRect`` 的渐变。
        """
        gradient = QLinearGradient(start, end)
        for at, color in self._stops:
            gradient.setColorAt(max(0.0, min(1.0, at / 100.0)), color)
        return gradient

    def _sample(self, percent: float) -> QColor:
        """在未量化的位置上做分段线性插值。"""
        first_at, first_color = self._stops[0]
        if percent <= first_at:
            return QColor(first_color)
        last_at, last_color = self._stops[-1]
        if percent >= last_at:
            return QColor(last_color)
        for (left_at, left_color), (right_at, right_color) in zip(
            self._stops, self._stops[1:], strict=False
        ):
            if left_at <= percent <= right_at:
                span = right_at - left_at
                ratio = 0.0 if span <= 0 else (percent - left_at) / span
                return _mix(left_color, right_color, ratio)
        return QColor(last_color)


def _mix(start: QColor, end: QColor, ratio: float) -> QColor:
    """两个颜色按比例线性插值（sRGB 分量直插）。"""
    return QColor(
        round(start.red() + (end.red() - start.red()) * ratio),
        round(start.green() + (end.green() - start.green()) * ratio),
        round(start.blue() + (end.blue() - start.blue()) * ratio),
    )
