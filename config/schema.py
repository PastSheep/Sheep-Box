"""配置数据结构定义。

使用 pydantic 声明式定义配置结构：
- 无默认值的字段为**必填**，缺失时严格报错；
- 有默认值的字段为**可选**，缺失时回退默认值。

该模块面向整个项目的通用配置中心，OCR 是当前首个业务模块，
后续其他模块配置在此扩展对应 Schema。
"""

from enum import Enum

from pydantic import BaseModel, Field


class ModelSpec(str, Enum):
    """OCR 模型规格档位。"""

    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"


class ModelMode(str, Enum):
    """启动时加载模型的方式。

    - 单规格：``tiny`` / ``small`` / ``medium``，仅加载对应规格一个实例；
    - ``all``：同时加载全部规格（占用更多内存/显存）。
    """

    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    ALL = "all"


class ModelSpecPaths(BaseModel):
    """单个模型规格对应的 ONNX 模型文件路径（PP-OCRv6）。"""

    det: str = Field(..., description="文本检测模型 det 的 onnx 路径")
    rec: str = Field(..., description="文本识别模型 rec 的 onnx 路径")
    dict_path: str = Field(
        ..., description="文本识别模型 rec 对应的字典（keys）文件路径，必填"
    )
    cls: str | None = Field(
        default=None, description="方向分类模型 cls 的 onnx 路径（可选）"
    )


class OcrModelConfig(BaseModel):
    """OCR 模型加载相关配置。"""

    mode: ModelMode = Field(
        default=ModelMode.SMALL, description="默认模型模式：tiny/small/medium/all"
    )
    default_spec: ModelSpec = Field(
        default=ModelSpec.SMALL,
        description="mode 非 all 时的默认加载规格",
    )
    models: dict[ModelSpec, ModelSpecPaths] = Field(
        ..., description="各规格的 det/rec/dict/cls 模型路径，必填"
    )


class OcrDeviceConfig(BaseModel):
    """OCR 运行设备配置。

    仅暴露 GPU 加速开关；自动探测与 CPU 回退由程序内部处理。
    首版仅面向 Windows：默认启用 GPU（需安装 DirectML 后端，
    ``onnxruntime-directml``），未安装或探测失败时自动回退 CPU。
    """

    gpu_enabled: bool = Field(default=True, description="是否启用 GPU 加速")


class OcrThresholdConfig(BaseModel):
    """OCR 识别阈值配置。"""

    text_score: float = Field(default=0.5, description="识别文本置信度阈值")
    box_thresh: float = Field(default=0.5, description="检测框置信度阈值")
    unclip_ratio: float = Field(default=1.6, description="检测框扩张比例")


class OcrConfig(BaseModel):
    """OCR 业务模块配置。"""

    model: OcrModelConfig = Field(..., description="模型加载配置，必填")
    device: OcrDeviceConfig = Field(
        default_factory=OcrDeviceConfig, description="设备配置"
    )
    thresholds: OcrThresholdConfig = Field(
        default_factory=OcrThresholdConfig, description="识别阈值配置"
    )
    language: str = Field(default="zh", description="识别语言，中文优先")


class AppConfig(BaseModel):
    """顶层配置结构。

    ``ocr`` 为必填段；未来新增模块在此追加可选字段。
    """

    ocr: OcrConfig = Field(..., description="OCR 模块配置，必填")
