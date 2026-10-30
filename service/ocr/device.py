"""设备适配：GPU 探测与 CPU 回退。

对外不提供用户开关：启动时自动探测可用的 Execution Provider，失败自动回退 CPU：
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


@lru_cache(maxsize=1)
def resolve_device() -> DevicePlan:
    """解析设备执行计划（自动探测 + CPU 回退）。

    探测结果被缓存，避免每次识别重复枚举 provider 并刷日志。

    Returns:
        设备执行计划，供 OCR 引擎加载时使用。
    """
    available = set(onnxruntime.get_available_providers())
    if _DIRECTML_EP in available:
        logger.info("device resolved: DirectML (GPU)")
        return DevicePlan(use_dml=True, use_cuda=False, device_name="directml")
    if _CUDA_EP in available:
        logger.info("device resolved: CUDA (GPU)")
        return DevicePlan(use_dml=False, use_cuda=True, device_name="cuda")

    logger.warning(
        "未检测到可用的 GPU 后端 " "(%s / %s 均不可用，available=%s)，回退 CPU",
        _CUDA_EP,
        _DIRECTML_EP,
        sorted(available),
    )
    return _cpu_plan()
