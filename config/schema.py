"""配置数据结构定义。

使用 pydantic 声明式定义配置结构：
- 无默认值的字段为**必填**，缺失时严格报错；
- 有默认值的字段为**可选**，缺失时回退默认值；
- 所有模型默认 ``extra="forbid"``：未知键直接报错，防止配置被静默写坏；
- ``OcrModelConfig`` 要求 tiny/small/medium 三档模型路径齐全，缺档直接报错；
- 识别阈值带取值范围约束（概率 0~1、扩张比例 >0），越界直接报错。

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
        """校验 tiny/small/medium 三档模型路径均已配置。

        三档必须齐全：即使当前 ``mode`` 只加载单档，运行时也可能切换档位或
        切到 ``all`` 模式；缺档只会在推理阶段以 ``KeyError`` 暴露，故前移到
        配置校验阶段直接拒绝。

        Returns:
            校验通过的模型配置自身。

        Raises:
            ValueError: 存在缺失档位；pydantic 会将其包装为
                ``ValidationError``，再由 :mod:`config.loader` 归一化为
                :class:`common.exceptions.ConfigError`。
        """
        missing = sorted(spec.value for spec in set(ModelSpec) - set(self.models))
        if missing:
            raise ValueError("模型档位缺失，无法加载: 缺少 " + ", ".join(missing))
        return self


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
    """返回 OCR 段可恢复的默认值（向后兼容入口）。

    默认值定义已收敛到 :mod:`config.defaults`，本函数仅保留旧导入路径
    ``from config.schema import ocr_defaults_update``，新代码请改用
    :func:`config.defaults.ocr_defaults_update`。函数内延迟导入：``config.defaults``
    依赖本模块的 pydantic 模型，模块顶部导入会构成循环依赖。

    Returns:
        嵌套 update 字典，可直接传给 :meth:`ConfigManager.save_ocr`。
    """
    from config.defaults import ocr_defaults_update as _ocr_defaults_update

    return _ocr_defaults_update()
