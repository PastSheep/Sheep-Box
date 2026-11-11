"""Windows 系统指标后端。

把 :mod:`service.sysinfo._win32` 返回的裸数据整理成采集器需要的形式：
- 适配器目录（含去重与虚拟适配器过滤）；
- GPU 引擎利用率按「适配器 / 物理引擎」聚合；
- CPU 时间与内存透传。

后端以 :class:`SystemMetricsBackend` 协议暴露，采集器只依赖协议，测试可注入
假实现而不触碰真实硬件。
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from typing import Any, Protocol

if sys.platform == "win32":  # pragma: no branch - 非 Windows 走 NullBackend
    from service.sysinfo._win32 import (
        GpuEngineQuery,
        NativeApiError,
        list_adapters,
        logical_processor_count,
        memory_bytes,
        system_times,
    )
else:  # pragma: no cover - 仅非 Windows 环境
    AdapterInfo = object  # type: ignore[assignment,misc]
    GpuEngineQuery = None  # type: ignore[assignment]
    NativeApiError = RuntimeError  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

__all__ = ["GpuReading", "NullBackend", "SystemMetricsBackend", "WindowsBackend"]


class GpuReading:
    """单次采样中一块 GPU 的读数。"""

    __slots__ = ("index", "name", "utilization_percent")

    def __init__(self, index: int, name: str, utilization_percent: float) -> None:
        self.index = index
        self.name = name
        self.utilization_percent = utilization_percent


class SystemMetricsBackend(Protocol):
    """采集后端契约：只返回原始量，不做任何业务判断。"""

    def system_times(self) -> tuple[int, int, int]:
        """返回累计 ``(idle, kernel, user)``，单位 100ns。"""
        ...

    def memory_bytes(self) -> tuple[int, int]:
        """返回 ``(物理总量, 可用量)``，单位字节。"""
        ...

    def logical_cores(self) -> int:
        """返回逻辑处理器数量。"""
        ...

    def collect_gpu(self) -> tuple[GpuReading, ...]:
        """采集一次各 GPU 的利用率；不可用时返回空元组。"""
        ...

    def close(self) -> None:
        """释放底层句柄；重复调用安全。"""
        ...


def _instance_parts(instance: str) -> tuple[tuple[int, int], int] | None:
    """从 PDH 实例名解析 ``(LUID, 物理引擎号)``。

    实例名形如 ``pid_1234_luid_0x00000000_0x0000E3AE_phys_0_eng_0_engtype_3D``。
    ``engtype`` 之后可能还带后缀（``engtype_Compute_1``），故只取 ``eng`` 后的编号，
    不按 ``_`` 切分的最后一段取类型名。

    Args:
        instance: PDH 实例名。

    Returns:
        ``((LUID 高位, LUID 低位), 引擎号)``；格式不符时返回 None。
    """
    parts = instance.split("_")
    try:
        luid_at = parts.index("luid")
        eng_at = parts.index("eng")
    except ValueError:
        return None
    if eng_at + 1 >= len(parts) or luid_at + 2 >= len(parts):
        return None
    try:
        high = int(parts[luid_at + 1], 16)
        low = int(parts[luid_at + 2], 16)
        engine = int(parts[eng_at + 1])
    except ValueError:
        return None
    return (high, low), engine


def _aggregate_gpu(
    rows: list[tuple[str, float]],
) -> dict[tuple[int, int], float]:
    """把原始实例列表聚合成「每个 LUID 最忙物理引擎」的利用率。

    口径与任务管理器一致：同一物理引擎上多个进程的占比先求和（同一进程的多个
    引擎实例也可能并存），截断到 100，再在各引擎之间取最大值。

    Args:
        rows: ``[(实例名, 利用率), ...]``。

    Returns:
        ``{LUID: 适配器级利用率}``。
    """
    per_engine: dict[tuple[tuple[int, int], int], float] = {}
    for instance, value in rows:
        parsed = _instance_parts(instance)
        if parsed is None:
            continue
        key, engine = parsed
        per_engine[(key, engine)] = per_engine.get((key, engine), 0.0) + value
    per_adapter: dict[tuple[int, int], float] = {}
    for (luid, _engine), value in per_engine.items():
        clamped = min(value, 100.0)
        if clamped > per_adapter.get(luid, 0.0):
            per_adapter[luid] = clamped
    return per_adapter


class WindowsBackend:
    """Windows 原生后端：PDH + kernel32 + DXGI。

    Args:
        enable_gpu: 是否启用 GPU 采集；关闭时不打开 PDH 查询、不枚举适配器。

    Note:
        适配器目录在构造时枚举一次（显卡热插拔/驱动重启后需重建采集器）。虚拟
        显示驱动（IddCx）可能以物理卡的描述注册多个 LUID，目录按
        ``(型号, 显存容量)`` 去重，每个组合只保留一个。
    """

    def __init__(self, enable_gpu: bool = True) -> None:
        self._query: object | None = None
        self._adapters: tuple[Any, ...] = ()
        self._luid_to_index: dict[tuple[int, int], int] = {}

        if not enable_gpu or sys.platform != "win32":
            return
        try:
            adapters = list_adapters()
        except Exception as exc:  # noqa: BLE001 - 适配器目录失败不应阻断采集
            logger.warning("DXGI 适配器枚举失败: %s", exc)
            adapters = []
        self._adapters = _dedupe_adapters(adapters)
        self._luid_to_index = {
            adapter.luid_key: index for index, adapter in enumerate(self._adapters)
        }
        if not self._adapters:
            return
        try:
            self._query = GpuEngineQuery()
        except NativeApiError as exc:
            logger.info("GPU 引擎计数器不可用，GPU 采集降级: %s", exc)

    @property
    def gpu_enabled(self) -> bool:
        """是否已成功建立 GPU 采集通道。"""
        return self._query is not None

    def system_times(self) -> tuple[int, int, int]:
        """返回累计 ``(idle, kernel, user)``。"""
        return system_times()

    def memory_bytes(self) -> tuple[int, int]:
        """返回 ``(物理总量, 可用量)``。"""
        return memory_bytes()

    def logical_cores(self) -> int:
        """返回逻辑处理器数量。"""
        return logical_processor_count()

    def collect_gpu(self) -> tuple[GpuReading, ...]:
        """采集各 GPU 利用率；未启用或读取失败时返回空元组。"""
        query = self._query
        if query is None:
            return ()
        try:
            rows = query.sample()  # type: ignore[attr-defined]
        except NativeApiError as exc:
            logger.warning("GPU 引擎采集失败: %s", exc)
            return ()
        per_adapter = _aggregate_gpu(rows)
        readings: list[GpuReading] = []
        for luid, value in per_adapter.items():
            index = self._luid_to_index.get(luid)
            if index is None:
                continue
            readings.append(
                GpuReading(
                    index=index,
                    name=_adapter_name(self._adapters[index]),
                    utilization_percent=round(float(value), 1),
                )
            )
        readings.sort(key=lambda reading: reading.index)
        return tuple(readings)

    def close(self) -> None:
        """释放 PDH 查询；重复调用安全。"""
        query = self._query
        self._query = None
        if query is not None:
            query.close()  # type: ignore[attr-defined]


def _adapter_name(adapter: Any) -> str:
    """读取适配器型号名；结构不符时返回空串。"""
    return str(getattr(adapter, "name", "") or "")


def _dedupe_adapters(adapters: Sequence[Any]) -> tuple[Any, ...]:
    """按 ``(型号, 专用显存, 共享内存)`` 去重。

    虚拟显示驱动（Todesk / MuMu / Oray 等）会以物理卡的描述注册额外 LUID，
    不去重会让状态栏多出若干恒为 0% 的重复项。同型号同容量的多块真卡会被误
    合并——这一场景罕见，且代价只是少显示一项，注释保留说明。

    Args:
        adapters: DXGI 返回的适配器列表。

    Returns:
        去重后的适配器元组。
    """
    seen: dict[tuple[str, int, int], Any] = {}
    for adapter in adapters:
        key = (
            _adapter_name(adapter),
            int(getattr(adapter, "dedicated_video_memory", 0) or 0),
            int(getattr(adapter, "shared_system_memory", 0) or 0),
        )
        seen.setdefault(key, adapter)
    return tuple(seen.values())


class NullBackend:
    """无采样能力的后端（非 Windows 或强制降级时使用）。"""

    def system_times(self) -> tuple[int, int, int]:
        """返回全零时间，等价于「无数据」。"""
        return 0, 0, 0

    def memory_bytes(self) -> tuple[int, int]:
        """返回全零内存，等价于「无数据」。"""
        return 0, 0

    def logical_cores(self) -> int:
        """返回 0 个逻辑核。"""
        return 0

    def collect_gpu(self) -> tuple[GpuReading, ...]:
        """无 GPU 数据。"""
        return ()

    def close(self) -> None:
        """无资源可释放。"""
