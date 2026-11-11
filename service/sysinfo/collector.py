"""设备资源采集器。

对外只有一个动作：**调用即采样**。不内置定时器、不跑后台线程、不保存历史、
不做阈值判断——采样节奏与告警策略都属于消费方（GUI 状态栏 / CLI / 测试）。

CPU 与 GPU 利用率都基于「两次采样之间的增量」，因此：
- 构造采集器时会先读一次 CPU 时间做基线，首次 :meth:`sample` 才有意义；
- GPU 计数器在构造时完成首次采集（PDH 要求），随后每次采样读区间均值；
- 采样间隔过短（< 500ms）读数会明显抖动，这是差分类计数器的固有性质。
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from common.exceptions import SystemInfoError
from service.sysinfo.models import CpuSample, GpuSample, MemorySample, SystemSnapshot

logger = logging.getLogger(__name__)

__all__ = ["SystemCollector"]


class SystemCollector:
    """设备级 CPU / 内存 / GPU 利用率采集器。

    Args:
        enable_gpu: 是否启用 GPU 采集。关闭后 :attr:`gpu_available` 恒为 False，
            且不会枚举适配器、不打开 PDH 查询。
        backend: 注入的采集后端（测试用）。为空时按平台自动选择：Windows 用
            原生后端，其他平台用空后端。

    Attributes:
        gpu_available: 是否成功建立 GPU 采集通道。
    """

    def __init__(
        self,
        enable_gpu: bool = True,
        *,
        backend: object | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._backend: object = (
            backend if backend is not None else self._make_backend(enable_gpu)
        )
        self._last_times: tuple[int, int, int] | None = None
        try:
            self._last_times = self._backend.system_times()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - 构造期失败延后到 sample 报错
            logger.warning("CPU 时间基线读取失败: %s", exc)

    @staticmethod
    def _make_backend(enable_gpu: bool) -> object:
        """按平台创建默认后端。"""
        if sys.platform != "win32":
            from service.sysinfo.backend import NullBackend

            return NullBackend()
        from service.sysinfo.backend import WindowsBackend

        return WindowsBackend(enable_gpu=enable_gpu)

    @property
    def gpu_available(self) -> bool:
        """是否已成功建立 GPU 采集通道。"""
        return bool(getattr(self._backend, "gpu_enabled", False))

    def sample(self) -> SystemSnapshot:
        """采集一帧。

        Returns:
            当前设备快照。

        Raises:
            SystemInfoError: CPU 或内存读取失败；GPU 失败只降级为空列表。
        """
        with self._lock:
            timestamp = time.time()
            times = self._read_times()
            cpu_percent = self._cpu_percent(times)
            memory = self._read_memory()
            gpus = self._read_gpus()
            return SystemSnapshot(
                timestamp=timestamp,
                cpu=CpuSample(
                    percent=cpu_percent,
                    logical_cores=self._read_cores(),
                ),
                memory=memory,
                gpus=gpus,
            )

    def _read_times(self) -> tuple[int, int, int]:
        """读取系统 CPU 时间，失败归一化为 SystemInfoError。"""
        try:
            times = self._backend.system_times()  # type: ignore[attr-defined]
        except Exception as exc:
            raise SystemInfoError(f"CPU 时间读取失败: {exc}") from exc
        return int(times[0]), int(times[1]), int(times[2])

    def _cpu_percent(self, times: tuple[int, int, int]) -> float:
        """按与上次采样的增量计算 CPU 占用百分比。

        ``kernel`` 已包含 ``idle``：忙时 = ``Δkernel + Δuser − Δidle``，
        总时 = ``Δkernel + Δuser``。首次采样无基线，返回 0.0。
        """
        previous = self._last_times
        self._last_times = times
        if previous is None:
            return 0.0
        delta_idle = times[0] - previous[0]
        delta_kernel = times[1] - previous[1]
        delta_user = times[2] - previous[2]
        total = delta_kernel + delta_user
        if total <= 0:
            return 0.0
        busy = max(total - delta_idle, 0)
        return round(min(busy / total * 100.0, 100.0), 1)

    def _read_memory(self) -> MemorySample:
        """读取内存并换算成采样模型。"""
        try:
            total, available = self._backend.memory_bytes()  # type: ignore[attr-defined]
        except Exception as exc:
            raise SystemInfoError(f"内存读取失败: {exc}") from exc
        used = max(total - available, 0)
        percent = round(used / total * 100.0, 1) if total > 0 else 0.0
        return MemorySample(
            total=total, used=used, available=available, percent=percent
        )

    def _read_cores(self) -> int:
        """读取逻辑处理器数量；失败时为 0。"""
        try:
            return int(self._backend.logical_cores())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 核数只是展示信息
            return 0

    def _read_gpus(self) -> tuple[GpuSample, ...]:
        """读取各 GPU 利用率；失败或未启用时为空。"""
        if self._closed:
            return ()
        try:
            readings = self._backend.collect_gpu()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - GPU 不是必需能力
            logger.warning("GPU 采集失败，本次降级为空: %s", exc)
            return ()
        return tuple(
            GpuSample(
                index=reading.index,
                name=reading.name,
                utilization_percent=reading.utilization_percent,
            )
            for reading in readings
        )

    def close(self) -> None:
        """释放后端资源；重复调用安全，之后采样只返回 CPU / 内存。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._backend.close()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - 关闭失败不影响后续使用
                logger.warning("后端关闭失败: %s", exc)

    def __enter__(self) -> SystemCollector:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
