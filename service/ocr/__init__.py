"""OCR 业务模块。

对外提供 :class:`OCRManager`，统一接口为字节流输入、结构化输出。
"""

from service.ocr.manager import OCRManager
from service.ocr.models import ModelSpec, OCRResult, OCRTextItem

__all__ = ["OCRManager", "ModelSpec", "OCRResult", "OCRTextItem"]
