"""设备适配：GPU 探测与 CPU 回退。

对外仅暴露 GPU 加速开关（``gpu_enabled``），自动探测与回退全部在内部处理：
- 开关关闭 → 纯 CPU；
- 开关开启 → 探测可用 Execution Provider：
    - Windows：优先 DirectML（``DmlExecutionProvider``，覆盖 AMD/NVIDIA/Intel GPU）；
    - 其次 CUDA（``CUDAExecutionProvider``，NVIDIA GPU）；
    - 均不可用 → 回退 CPU 并记录告警。

注意：GPU 能力依赖对应的 onnxruntime 后端包（``onnxruntime-directml`` /
``onnxruntime-gpu``，见 ``pyproject.toml`` 的 ``ocr-gpu-*`` extra），
未安装 GPU 后端时自动回退 CPU。
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import onnxruntime

logger = logging.getLogger(__name__)

_CUDA_EP = "CUDAExecutionProvider"
_DIRECTML_EP = "DmlExecutionProvider"


@dataclass(frozen=True)
class DevicePlan:
    """解析出的设备执行计划。

    Attributes:
        use_dml: 是否启用 DirectML 后端。
        use_cuda: 是否启用 CUDA 后端。
        device_name: 生效设备描述（用于日志）。
    """

    use_dml: bool = False
    use_cuda: bool = False
    device_name: str = "cpu"


def _cpu_plan() -> DevicePlan:
    """构造纯 CPU 执行计划。"""
    return DevicePlan(use_dml=False, use_cuda=False, device_name="cpu")


@lru_cache(maxsize=4)
def resolve_device(gpu_enabled: bool) -> DevicePlan:
    """根据 GPU 开关解析设备执行计划（含自动探测与 CPU 回退）。

    探测结果被缓存（同一开关取值只探测一次），避免每次识别重复枚举
    provider 并刷日志。

    Args:
        gpu_enabled: 用户是否启用 GPU 加速。

    Returns:
        设备执行计划，供 OCR 引擎加载时使用。
    """
    if not gpu_enabled:
        return _cpu_plan()

    available = set(onnxruntime.get_available_providers())
    if _DIRECTML_EP in available:
        logger.info("device resolved: DirectML (GPU)")
        return DevicePlan(use_dml=True, use_cuda=False, device_name="directml")
    if _CUDA_EP in available:
        logger.info("device resolved: CUDA (GPU)")
        return DevicePlan(use_dml=False, use_cuda=True, device_name="cuda")

    logger.warning(
        "gpu_enabled=True 但未检测到可用的 GPU 后端 "
        "(%s / %s 均不可用，available=%s)，回退 CPU",
        _CUDA_EP,
        _DIRECTML_EP,
        sorted(available),
    )
    return _cpu_plan()
