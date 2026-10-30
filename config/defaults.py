"""配置默认值的单一来源。

CLI/GUI 的「恢复默认」统一从本模块取默认值，避免在多个入口重复手抄一份
字面量导致与 schema 漂移。所有取值均由 :mod:`config.schema` 的 pydantic
模型默认值派生（枚举成员、模型实例、字段默认值），schema 调整后无需再改
本模块。
"""

from typing import Any

from config.schema import (
    ModelMode,
    ModelSpec,
    OcrConfig,
    OcrThresholdConfig,
)

__all__ = ["ocr_defaults_update"]


def ocr_defaults_update() -> dict[str, Any]:
    """返回 OCR 配置段的默认值（嵌套 update 字典，可直接传给 ConfigManager.save_ocr）。

    仅包含可恢复的运行参数（mode/default_spec/thresholds/language），
    不包含 ``models``：模型路径属于部署相关配置，应保留当前值，避免「恢复
    默认」把用户的模型路径重置成默认值。

    Returns:
        嵌套 update 字典，结构与 ``config.yaml`` 的 ``ocr`` 段一致，例如::

            {
                "model": {"mode": "small", "default_spec": "small"},
                "thresholds": {
                    "text_score": 0.5,
                    "box_thresh": 0.5,
                    "unclip_ratio": 1.6,
                },
                "language": "zh",
            }
    """
    return {
        "model": {
            "mode": ModelMode.SMALL.value,
            "default_spec": ModelSpec.SMALL.value,
        },
        "thresholds": OcrThresholdConfig().model_dump(),
        "language": OcrConfig.model_fields["language"].default,
    }
