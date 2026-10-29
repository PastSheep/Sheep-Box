"""配置数据结构定义。

使用 pydantic 声明式定义配置结构：
- 无默认值的字段为**必填**，缺失时严格报错；
- 有默认值的字段为**可选**，缺失时回退默认值；
- 所有模型默认 ``extra="forbid"``：未知键直接报错，防止配置被静默写坏。

该模块面向整个项目的通用配置中心，OCR 是当前首个业务模块，
后续其他模块配置在此扩展对应 Schema。
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelSpec(StrEnum):
    """OCR 模型规格档位。"""

    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"


# 模型档位全集；用于校验 models 覆盖度（定义于 ModelSpec 之后）
_REQUIRED_SPECS = (ModelSpec.TINY, ModelSpec.SMALL, ModelSpec.MEDIUM)


class ModelMode(StrEnum):
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

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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

    @model_validator(mode="after")
    def _check_models_coverage(self) -> "OcrModelConfig":
        """校验实际会加载的模型档位存在（修复构造期 KeyError）。

        - 非 all 模式：所需档 = ``mode`` 对应的单规格；
        - all 模式：需要 tiny/small/medium 全部档位。
        """
        required = (
            set(_REQUIRED_SPECS)
            if self.mode == ModelMode.ALL
            else {ModelSpec(self.mode.value)}
        )
        missing = [spec.value for spec in required if spec not in self.models]
        if missing:
            raise ValueError("模型档位缺失，无法加载: 缺少 " + ", ".join(missing))
        return self


class OcrDeviceConfig(BaseModel):
    """OCR 运行设备配置。

    仅暴露 GPU 加速开关；自动探测与 CPU 回退由程序内部处理。
    首版仅面向 Windows：默认启用 GPU（需安装 DirectML 后端，
    ``onnxruntime-directml``），未安装或探测失败时自动回退 CPU。
    """

    model_config = ConfigDict(extra="forbid")

    gpu_enabled: bool = Field(default=True, description="是否启用 GPU 加速")


class OcrThresholdConfig(BaseModel):
    """OCR 识别阈值配置。"""

    model_config = ConfigDict(extra="forbid")

    text_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="识别文本置信度阈值（0~1）"
    )
    box_thresh: float = Field(
        default=0.5, ge=0.0, le=1.0, description="检测框置信度阈值（0~1）"
    )
    unclip_ratio: float = Field(default=1.6, gt=0.0, description="检测框扩张比例（>0）")


class OcrConfig(BaseModel):
    """OCR 业务模块配置。"""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    ocr: OcrConfig = Field(..., description="OCR 模块配置，必填")


def ocr_defaults_update() -> dict[str, object]:
    """返回 OCR 段可恢复的默认值（单一来源，供 CLI/GUI「恢复默认」派生）。

    仅包含可恢复的运行参数（mode/default_spec/device/thresholds/language），
    不包含 ``models``（模型路径应保留当前值，避免误覆盖）。
    """
    return {
        "model": {
            "mode": OcrModelConfig.model_fields["mode"].default.value,
            "default_spec": OcrModelConfig.model_fields["default_spec"].default.value,
        },
        "device": {"gpu_enabled": OcrDeviceConfig.model_fields["gpu_enabled"].default},
        "thresholds": {
            "text_score": OcrThresholdConfig.model_fields["text_score"].default,
            "box_thresh": OcrThresholdConfig.model_fields["box_thresh"].default,
            "unclip_ratio": OcrThresholdConfig.model_fields["unclip_ratio"].default,
        },
        "language": OcrConfig.model_fields["language"].default,
    }
