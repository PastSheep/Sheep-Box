"""OCR 引擎封装：基于 RapidOCR v3（ONNX Runtime）的识别实现。

将 RapidOCR v3 的底层返回结构（``RapidOCROutput``）转换为模块统一的结构化输出，
并支持按模型规格传入对应的本地 PP-OCRv6 ONNX 模型路径、字典文件与设备执行计划。

初始化顺序：先校验模型文件存在（缺失直接失败，不做无意义的 GPU→CPU 重试），
再组装 RapidOCR params；GPU 初始化失败时自动去掉 GPU 后端开关、回退 CPU 重试一次。
"""

import logging
from pathlib import Path
from types import TracebackType
from typing import Any

from rapidocr import EngineType, OCRVersion, RapidOCR
from rapidocr.utils.output import RapidOCROutput

from common.exceptions import OcrEngineError
from config.schema import ModelSpec, ModelSpecPaths, OcrThresholdConfig
from service.ocr.device import DevicePlan
from service.ocr.models import BBox, OCRTextItem

logger = logging.getLogger(__name__)

_GPU_PARAM_PREFIX = "EngineConfig.onnxruntime."


def _build_params(
    paths: ModelSpecPaths, device: DevicePlan, thresholds: OcrThresholdConfig
) -> dict[str, Any]:
    """组装 RapidOCR v3 params。

    Args:
        paths: 该规格的 det / rec / cls 模型路径与 rec 字典文件。
        device: 设备执行计划（GPU / CPU）。
        thresholds: 识别阈值配置。

    Returns:
        RapidOCR ``params`` 参数字典（键名与 rapidocr 3.10.0 一致）。
    """
    params: dict[str, Any] = {
        # 全局：识别置信度阈值
        "Global.text_score": thresholds.text_score,
        # 检测（DBNet）
        "Det.engine_type": EngineType.ONNXRUNTIME,
        "Det.model_path": paths.det,
        "Det.box_thresh": thresholds.box_thresh,
        "Det.unclip_ratio": thresholds.unclip_ratio,
        # 识别（CRNN）
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Rec.model_path": paths.rec,
        "Rec.rec_keys_path": paths.dict_path,
    }
    # 方向分类（可选）：v6 采用 PP-OCRv5 的 cls 模型，三档共用；
    # 输入 shape 由 ocr_version 决定（PP-OCRv5 → [3, 80, 160]）
    if paths.cls:
        params["Cls.engine_type"] = EngineType.ONNXRUNTIME
        params["Cls.ocr_version"] = OCRVersion.PPOCRV5
        params["Cls.model_path"] = paths.cls

    # 设备：仅向引擎注入本次生效的后端开关（DirectML / CUDA）
    if device.use_dml:
        params["EngineConfig.onnxruntime.use_dml"] = True
    elif device.use_cuda:
        params["EngineConfig.onnxruntime.use_cuda"] = True
    return params


def _check_model_files(paths: ModelSpecPaths) -> None:
    """校验模型文件存在。

    在构造引擎前完成校验：缺文件属于配置 / 部署问题，不应被当作 GPU 初始化
    失败而触发 CPU 重试。

    Args:
        paths: 该规格的模型路径配置。

    Raises:
        OcrEngineError: det / rec / dict（及非空 cls）文件缺失。
    """
    candidates = [paths.det, paths.rec, paths.dict_path]
    if paths.cls:
        candidates.append(paths.cls)
    for model_path in candidates:
        if not Path(model_path).exists():
            raise OcrEngineError(f"模型文件不存在: {model_path}")


class OCREngine:
    """封装单个模型规格的识别引擎（rapidocr v3 params API）。

    Args:
        spec: 模型规格（tiny / small / medium）。
        paths: 该规格的 det / rec / cls 模型路径与 rec 字典文件。
        device: 设备执行计划（GPU / CPU）。
        thresholds: 识别阈值配置。

    Raises:
        OcrEngineError: 模型文件缺失，或引擎初始化失败（GPU 回退 CPU 后仍失败）。
    """

    def __init__(
        self,
        spec: ModelSpec,
        paths: ModelSpecPaths,
        device: DevicePlan,
        thresholds: OcrThresholdConfig,
    ) -> None:
        _check_model_files(paths)
        params = _build_params(paths, device, thresholds)
        logger.info(
            "loading OCR engine: spec=%s device=%s", spec.value, device.device_name
        )
        self._spec = spec
        self._engine: RapidOCR | None = self._init_engine(params, device)

    @staticmethod
    def _init_engine(params: dict[str, Any], device: DevicePlan) -> RapidOCR:
        """创建 RapidOCR 实例；GPU 初始化失败时自动回退 CPU 重试一次。

        Args:
            params: 完整参数（含 GPU 后端开关）。
            device: 设备执行计划。

        Returns:
            初始化成功的 RapidOCR 实例。

        Raises:
            OcrEngineError: 本就使用 CPU 且失败，或 GPU 回退 CPU 后仍失败。
        """
        try:
            return RapidOCR(params=params)
        except Exception as exc:
            if not (device.use_dml or device.use_cuda):
                raise OcrEngineError("OCR 引擎初始化失败") from exc
            logger.warning("GPU 初始化失败，回退 CPU", exc_info=True)
            cpu_params = {
                key: value
                for key, value in params.items()
                if not key.startswith(_GPU_PARAM_PREFIX)
            }
            try:
                return RapidOCR(params=cpu_params)
            except Exception as cpu_exc:
                raise OcrEngineError("OCR 引擎初始化失败") from cpu_exc

    @property
    def spec(self) -> ModelSpec:
        """当前引擎的模型规格。"""
        return self._spec

    def recognize(self, image_bytes: bytes) -> tuple[list[OCRTextItem], float]:
        """识别单张图片字节流。

        Args:
            image_bytes: 图片原始字节。

        Returns:
            ``(items, elapsed)``，items 为识别文本行列表，elapsed 为耗时（秒）。

        Raises:
            OcrEngineError: 引擎已通过 :meth:`close` 关闭，或底层推理失败。
        """
        engine = self._engine
        if engine is None:
            raise OcrEngineError("OCR 引擎已关闭")
        try:
            result = engine(image_bytes)
        except Exception as exc:
            logger.exception("OCR 推理失败: spec=%s", self._spec.value)
            raise OcrEngineError("OCR 推理失败") from exc
        if not isinstance(result, RapidOCROutput) or not result.txts:
            return [], getattr(result, "elapse", 0.0)
        if result.boxes is None or result.scores is None:
            return [], getattr(result, "elapse", 0.0)

        # 三元组长度应一致；不一致时取最短并告警，避免静默截断
        n = min(len(result.boxes), len(result.txts), len(result.scores))
        if n < len(result.txts):
            logger.warning(
                "OCR 结果长度不一致 boxes=%d txts=%d scores=%d，取前 %d 项",
                len(result.boxes),
                len(result.txts),
                len(result.scores),
                n,
            )
        items: list[OCRTextItem] = [
            OCRTextItem(text=text, bbox=_to_bbox(box), score=float(score))
            for box, text, score in zip(
                result.boxes[:n], result.txts[:n], result.scores[:n], strict=True
            )
        ]
        return items, result.elapse

    def close(self) -> None:
        """释放引擎持有的资源。

        受第三方限制（rapidocr 3.10.0 的 ONNX Runtime 后端无显式释放 API），
        置空底层引用，实际内存由 GC 回收；重复调用安全。
        """
        self._engine = None

    def __enter__(self) -> "OCREngine":
        """进入上下文，返回引擎自身。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """退出上下文时释放底层引用。"""
        self.close()


def _to_bbox(box: Any) -> BBox:
    """将 RapidOCR 返回的四点多边形坐标转换为模块统一的 BBox 结构。"""
    return [[float(px), float(py)] for px, py in box]
