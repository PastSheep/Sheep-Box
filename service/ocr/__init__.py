"""OCR 业务模块。

对外提供 :class:`OCRManager`，统一接口为字节流输入、结构化输出；
同时导出引擎层异常，便于调用方区分「引擎初始化/推理失败」与普通业务失败。

``service.ocr.__init__`` 会被轻量导入（如 ``from service.ocr.models import
OCRResult``）触发，因此 ``OCRManager`` 与 ``OcrEngineError`` 采用 **按需惰性
导出**（PEP 562）：首次访问属性时才导入，避免仅用数据模型时连带加载
rapidocr / onnxruntime 等重量依赖。``from service.ocr.manager import
OCRManager`` 的显式路径不受影响。
"""

from typing import TYPE_CHECKING

from service.ocr.models import ModelSpec, OCRResult, OCRTextItem

if TYPE_CHECKING:  # 仅类型检查可见，运行时不触发重量依赖导入
    from common.exceptions import OcrEngineError
    from service.ocr.manager import OCRManager

__all__ = ["ModelSpec", "OCRManager", "OCRResult", "OCRTextItem", "OcrEngineError"]


def __getattr__(name: str) -> object:
    """按需导入重量级导出（PEP 562），保持 ``from service.ocr import X`` 契约。

    Args:
        name: 属性名。

    Returns:
        对应的导出对象。

    Raises:
        AttributeError: 属性不存在。
    """
    if name == "OCRManager":
        from service.ocr.manager import OCRManager

        return OCRManager
    if name == "OcrEngineError":
        from common.exceptions import OcrEngineError

        return OcrEngineError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
