"""OCR 引擎封装：基于 RapidOCR v3（ONNX Runtime）的识别实现。

将 RapidOCR v3 的底层返回结构（``RapidOCROutput``）转换为模块统一的结构化输出，
并支持按模型规格传入对应的本地 PP-OCRv6 ONNX 模型路径、字典文件与设备执行计划。
"""

import logging
from typing import Any

from rapidocr import EngineType, OCRVersion, RapidOCR
from rapidocr.utils.output import RapidOCROutput

from config.schema import ModelSpec, ModelSpecPaths, OcrThresholdConfig
from service.ocr.device import DevicePlan
from service.ocr.models import BBox, OCRTextItem

logger = logging.getLogger(__name__)


class OCREngine:
    """封装单个模型规格的识别引擎（rapidocr v3 params API）。

    Args:
        spec: 模型规格（tiny / small / medium）。
        paths: 该规格的 det / rec / cls 模型路径与 rec 字典文件。
        device: 设备执行计划（GPU / CPU）。
        thresholds: 识别阈值配置。
    """

    def __init__(
        self,
        spec: ModelSpec,
        paths: ModelSpecPaths,
        device: DevicePlan,
        thresholds: OcrThresholdConfig,
    ) -> None:
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

        logger.info(
            "loading OCR engine: spec=%s device=%s", spec.value, device.device_name
        )
        self._spec = spec
        self._engine: RapidOCR | None = RapidOCR(params=params)

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
            RuntimeError: 引擎已通过 :meth:`close` 关闭。
        """
        engine = self._engine
        if engine is None:
            raise RuntimeError("OCR 引擎已关闭，无法识别")
        result = engine(image_bytes)
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

        受第三方限制（rapidocr 3.10.0 的 ONNX Runtime 后端无 ``close()``），
        置空底层引用并提示 GC 回收。
        """
        self._engine = None


def _to_bbox(box: Any) -> BBox:
    """将 RapidOCR 返回的四点多边形坐标转换为模块统一的 BBox 结构。"""
    return [[float(px), float(py)] for px, py in box]
