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


class Theme(StrEnum):
    """界面主题（黑白双主题）。"""

    LIGHT = "light"
    DARK = "dark"


class GradientStop(BaseModel):
    """利用率渐变的一个颜色锚点。

    锚点数量不固定：轨道是「位置 → 颜色」的分段线性渐变，相邻锚点之间按位置
    插值。消费方（状态栏的压力点）与设置页控件用的是同一份锚点，改配置即同时
    影响展示与编辑预览。
    """

    model_config = ConfigDict(extra="forbid")

    at: float = Field(
        ..., ge=0.0, le=100.0, description="锚点位置（利用率百分比 0~100）"
    )
    color: str = Field(
        ..., pattern=r"^#[0-9A-Fa-f]{6}$", description="锚点颜色，格式 #RRGGBB"
    )


def _default_gradient_stops() -> list[GradientStop]:
    """默认四段锚点：低负载绿 → 中段黄 → 高负载红。

    Returns:
        0 / 50 / 80 / 100 四个锚点，100 处重复红色以让高负载区间保持纯红。
    """
    return [
        GradientStop(at=0.0, color="#17A05E"),
        GradientStop(at=50.0, color="#E0A008"),
        GradientStop(at=80.0, color="#D94A4A"),
        GradientStop(at=100.0, color="#D94A4A"),
    ]


class StatusBarConfig(BaseModel):
    """底部状态栏配置（刷新节奏 + 压力着色）。"""

    model_config = ConfigDict(extra="forbid")

    refresh_interval_ms: int = Field(
        default=1000,
        ge=250,
        le=10000,
        description="采样与刷新间隔（毫秒）；500ms 以下差分读数会明显抖动",
    )
    gradient_stops: list[GradientStop] = Field(
        default_factory=_default_gradient_stops,
        description="利用率 → 颜色的渐变锚点，三个指标共用一套",
    )

    @model_validator(mode="after")
    def _check_stops(self) -> "StatusBarConfig":
        """校验锚点数量与唯一性。

        Returns:
            校验通过的自身。

        Raises:
            ValueError: 锚点少于 2 个（无法构成渐变）或存在重复位置。
        """
        if len(self.gradient_stops) < 2:
            raise ValueError("渐变锚点至少需要 2 个（起点与终点）")
        positions = [stop.at for stop in self.gradient_stops]
        if len(set(positions)) != len(positions):
            raise ValueError("渐变锚点位置不可重复")
        return self


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
        description="all 模式下的默认生效规格（非 all 时由 mode 决定档位）",
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


class AppSettingsConfig(BaseModel):
    """程序级偏好配置（由设置界面承载）。"""

    model_config = ConfigDict(extra="forbid")

    ui_language: str = Field(
        default="zh_CN", description="界面语言（i18n），缺省 zh_CN"
    )
    theme: Theme = Field(default=Theme.LIGHT, description="界面主题（黑白），缺省浅色")
    status_bar: StatusBarConfig = Field(
        default_factory=StatusBarConfig, description="底部状态栏（刷新节奏与压力着色）"
    )


class AppConfig(BaseModel):
    """顶层配置结构。

    ``ocr`` 为必填段；``app`` 为程序级偏好（可选，含界面语言），
    未来新增模块在此追加可选字段。
    """

    model_config = ConfigDict(extra="forbid")

    ocr: OcrConfig = Field(..., description="OCR 模块配置，必填")
    app: AppSettingsConfig = Field(
        default_factory=AppSettingsConfig, description="程序级偏好配置"
    )


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
