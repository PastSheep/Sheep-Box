"""系统信息基础能力模块。

与 ``service/ocr`` 平级：只提供设备级资源采集（CPU / 内存 / GPU），不承载业务
判定。采样频率、阈值告警、界面展示，都由消费该快照的模块自行决定。

``SystemCollector`` 采用 PEP 562 按需导出：只取数据模型（``SystemSnapshot`` 等）
时不加载 ctypes 绑定与 PDH 句柄。显式路径
``from service.sysinfo.collector import SystemCollector`` 不受影响。
"""

from typing import TYPE_CHECKING

from service.sysinfo.models import CpuSample, GpuSample, MemorySample, SystemSnapshot

if TYPE_CHECKING:  # 仅类型检查可见，运行时不触发后端导入
    from common.exceptions import SystemInfoError
    from service.sysinfo.collector import SystemCollector

__all__ = [
    "CpuSample",
    "GpuSample",
    "MemorySample",
    "SystemCollector",
    "SystemInfoError",
    "SystemSnapshot",
]


def __getattr__(name: str) -> object:
    """按需导入采集器与异常（PEP 562），保持 ``from service.sysinfo import X`` 契约。

    Args:
        name: 属性名。

    Returns:
        对应的导出对象。

    Raises:
        AttributeError: 属性不存在。
    """
    if name == "SystemCollector":
        from service.sysinfo.collector import SystemCollector

        return SystemCollector
    if name == "SystemInfoError":
        from common.exceptions import SystemInfoError

        return SystemInfoError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
