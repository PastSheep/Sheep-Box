"""OCR 引擎封装：基于 RapidOCR（ONNX Runtime）的识别实现。

将 RapidOCR 的底层返回结构转换为模块统一的结构化输出，
并支持按模型规格传入对应的 ONNX 模型路径与设备执行计划。
"""

import logging
from typing import Any

from rapidocr_onnxruntime import RapidOCR

from config.schema import ModelSpec, ModelSpecPaths, OcrThresholdConfig
from service.ocr.device import DevicePlan
from service.ocr.models import BBox, OCRTextItem

logger = logging.getLogger(__name__)


class OCREngine:
    """封装单个模型规格的识别引擎。

    Args:
        spec: 模型规格（tiny / small / medium）。
        paths: 该规格的 det / rec / cls 模型路径。
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
        kwargs: dict[str, Any] = {}
        kwargs["det_model_path"] = paths.det
        kwargs["rec_model_path"] = paths.rec
        if paths.cls:
            kwargs["cls_model_path"] = paths.cls

        # GPU 开关需逐模块（det/rec/cls）传入
        if device.use_dml:
            kwargs.update(det_use_dml=True, rec_use_dml=True, cls_use_dml=True)
        elif device.use_cuda:
            kwargs.update(det_use_cuda=True, rec_use_cuda=True, cls_use_cuda=True)

        # 阈值收敛到引擎初始化配置
        kwargs["det_box_thresh"] = thresholds.box_thresh
        kwargs["det_unclip_ratio"] = thresholds.unclip_ratio
        kwargs["text_score"] = thresholds.text_score

        logger.info(
            "loading OCR engine: spec=%s device=%s", spec.value, device.device_name
        )
        self._spec = spec
        self._engine = RapidOCR(**kwargs)

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
        """
        result, elapse = self._engine(image_bytes)
        if not result:
            return [], 0.0

        items: list[OCRTextItem] = []
        for entry in result:
            box, text, score = entry[0], entry[1], entry[2]
            items.append(OCRTextItem(text=text, bbox=_to_bbox(box), score=float(score)))
        return items, _sum_elapse(elapse)


def _sum_elapse(elapse: Any) -> float:
    """将 RapidOCR 返回的耗时（可能是各阶段耗时列表）折算为总耗时（秒）。"""
    if isinstance(elapse, (list, tuple)):
        return sum(float(x) for x in elapse if x is not None)
    return float(elapse or 0.0)


def _to_bbox(box: Any) -> BBox:
    """将 RapidOCR 返回的坐标转换为模块统一的 BBox 结构。"""
    return [[float(px), float(py)] for px, py in box]
