"""OCR 结构化输出与规格枚举。

对外契约统一为字节流输入、结构化输出：
- 输入：图片原始字节（``bytes``）或 base64 字符串；
- 输出：:class:`OCRResult`，包含逐行 :class:`OCRTextItem`（文本 / 坐标框 / 置信度）。

模块只负责识别与结构化输出；文本清洗 / 后处理由未来消费结构化结果的
功能模块自行实现，不在本模块内置清洗规则。
"""

from dataclasses import dataclass, field

from config.schema import ModelSpec

__all__ = ["BBox", "ModelSpec", "OCRResult", "OCRTextItem"]


BBox = list[list[int | float]]
"""坐标框类型：四边形 4 个顶点，形如 ``[[x1, y1], [x2, y2], ...]``。"""


@dataclass(frozen=True)
class OCRTextItem:
    """单条识别结果。

    Attributes:
        text: 识别文本。
        bbox: 文本所在四边形坐标。
        score: 识别置信度（0~1）。
    """

    text: str
    bbox: BBox
    score: float


@dataclass(frozen=True)
class OCRResult:
    """一次识别的结构化结果。

    Attributes:
        items: 识别出的文本行列表（按版面顺序）。
        elapsed: 本次识别耗时（秒）。
    """

    items: list[OCRTextItem] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def text(self) -> str:
        """按行拼接的纯文本（以换行分隔，未清洗）。"""
        return "\n".join(item.text for item in self.items)

    def __bool__(self) -> bool:
        """是否识别出内容。"""
        return bool(self.items)
