"""系统资源采集的数据模型。

采样结果只描述「看到了什么」：不含阈值、颜色、告警等级或历史——利用率低到
什么程度算异常、显示成什么颜色、多久采一次，全部由消费方决定。

首版只暴露任务管理器口径的三项指标（CPU / 内存 / GPU 利用率）；温度、功耗、
显存占用等需要厂商私有接口或 DXGI 额外查询的指标不在本模块职责内。
"""

from dataclasses import dataclass

__all__ = ["CpuSample", "GpuSample", "MemorySample", "SystemSnapshot"]


@dataclass(frozen=True)
class CpuSample:
    """CPU 占用采样。

    Attributes:
        percent: 全核总占用百分比（0~100）。语义是「距上一次采样」区间的平均值，
            不是瞬时值：两次采样间隔越短读数越不稳定，建议间隔 ≥ 500ms。
            构造后立刻采样会得到接近 0 的值，消费方应丢弃首帧。
        logical_cores: 逻辑处理器数量（含超线程）；取不到时为 0。
    """

    percent: float
    logical_cores: int


@dataclass(frozen=True)
class MemorySample:
    """物理内存占用采样。

    Attributes:
        total: 物理内存总容量（字节）。
        used: 已用容量（字节），等于 ``total - available``。
        available: 可用物理内存（字节）。
        percent: 已用百分比（0~100）。
    """

    total: int
    used: int
    available: int
    percent: float


@dataclass(frozen=True)
class GpuSample:
    """单块物理 GPU 的利用率采样。

    Attributes:
        index: 展示序号（0 起），按适配器枚举顺序排列，不是设备 ID。
        name: 适配器型号名；DXGI 不可用时为空字符串。
        utilization_percent: 适配器级利用率（0~100）。口径为「最忙的物理引擎」
            的占用率，与任务管理器性能页一致：同一引擎上的多个进程先求和再
            截断到 100，再在各引擎之间取最大值。
    """

    index: int
    name: str
    utilization_percent: float


@dataclass(frozen=True)
class SystemSnapshot:
    """一次采样的完整设备快照。

    Attributes:
        timestamp: 采样时刻的 Unix 时间戳（秒）。
        cpu: CPU 采样。
        memory: 内存采样。
        gpus: 各物理 GPU 采样，按枚举顺序；无可用 GPU 时为空元组。
    """

    timestamp: float
    cpu: CpuSample
    memory: MemorySample
    gpus: tuple[GpuSample, ...] = ()

    @property
    def gpu_available(self) -> bool:
        """是否存在可采集的 GPU。"""
        return bool(self.gpus)
