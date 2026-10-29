"""设置界面控制器。

负责设置界面与通用配置中心之间的桥接：
- 读取当前生效的 OCR 配置，转为表单可编辑的扁平值；
- 校验用户输入（枚举合法、阈值范围、语言非空）；
- 写回 ``config.yaml``（经 :meth:`ConfigManager.save_ocr`，保留注释并校验）；
- 恢复 schema 默认值（模型路径保留当前）。

本模块**不依赖 Qt**，便于纯逻辑单元测试。
"""

from collections.abc import Mapping
from typing import cast

from config.manager import ConfigManager
from config.schema import ModelMode, ModelSpec, ModelSpecPaths, ocr_defaults_update

__all__ = ["SettingsController"]


class SettingsController:
    """设置界面控制器（无 Qt 依赖）。"""

    def __init__(self, config_manager: ConfigManager) -> None:
        self._cm = config_manager

    def load(self) -> dict[str, object]:
        """读取当前生效 OCR 配置，返回表单可编辑的扁平值。

        Returns:
            键：``mode`` / ``default_spec`` / ``gpu_enabled`` / ``text_score`` /
            ``box_thresh`` / ``unclip_ratio`` / ``language`` / ``models``（只读展示）。
        """
        ocr = self._cm.ocr()
        return {
            "mode": ocr.model.mode.value,
            "default_spec": ocr.model.default_spec.value,
            "gpu_enabled": ocr.device.gpu_enabled,
            "text_score": ocr.thresholds.text_score,
            "box_thresh": ocr.thresholds.box_thresh,
            "unclip_ratio": ocr.thresholds.unclip_ratio,
            "language": ocr.language,
            "models": self._models_dict(ocr.model.models),
        }

    @staticmethod
    def _models_dict(
        models: Mapping[ModelSpec, ModelSpecPaths],
    ) -> dict[str, dict[str, object]]:
        """把各规格模型路径展平为字典（只读展示用）。"""
        result: dict[str, dict[str, object]] = {}
        for spec, paths in models.items():
            result[spec.value] = {
                "det": paths.det,
                "rec": paths.rec,
                "dict_path": paths.dict_path,
                "cls": paths.cls,
            }
        return result

    @staticmethod
    def _float(value: object) -> float:
        """把表单数值安全转 ``float``（调用前应已通过 ``validate_values``）。"""
        return float(value) if isinstance(value, (int, float)) else 0.0

    def validate_values(self, values: dict[str, object]) -> list[str]:
        """校验表单提交值，返回错误消息列表（空列表表示合法）。"""
        errors: list[str] = []
        mode = values.get("mode")
        try:
            ModelMode(mode)  # type: ignore[arg-type]
        except (KeyError, ValueError):
            errors.append(
                f"非法模型模式: {mode!r}（可选 {[m.value for m in ModelMode]}）"
            )
        spec = values.get("default_spec")
        try:
            ModelSpec(spec)  # type: ignore[arg-type]
        except (KeyError, ValueError):
            errors.append(
                f"非法默认规格: {spec!r}（可选 {[m.value for m in ModelSpec]}）"
            )
        for name, lo, hi in (("text_score", 0.0, 1.0), ("box_thresh", 0.0, 1.0)):
            v = values.get(name)
            if not isinstance(v, (int, float)) or not (lo <= v <= hi):
                errors.append(f"{name} 需在 {lo:g}~{hi:g} 之间")
        ratio = values.get("unclip_ratio")
        if not isinstance(ratio, (int, float)) or ratio <= 0:
            errors.append("unclip_ratio 需大于 0")
        lang = values.get("language")
        if lang is None or not str(lang).strip():
            errors.append("语言不能为空")
        return errors

    def build_update(self, values: dict[str, object]) -> dict[str, object]:
        """由表单值构造嵌套写回字典。"""
        return {
            "model": {
                "mode": values["mode"],
                "default_spec": values["default_spec"],
            },
            "device": {"gpu_enabled": bool(values["gpu_enabled"])},
            "thresholds": {
                "text_score": self._float(values["text_score"]),
                "box_thresh": self._float(values["box_thresh"]),
                "unclip_ratio": self._float(values["unclip_ratio"]),
            },
            "language": str(values["language"]).strip(),
        }

    def save(self, values: dict[str, object]) -> None:
        """校验并写回配置。

        Raises:
            ValueError: 校验失败，消息以 ``; `` 连接各错误。
        """
        errors = self.validate_values(values)
        if errors:
            raise ValueError("; ".join(errors))
        self._cm.save_ocr(self.build_update(values))

    def defaults(self) -> dict[str, object]:
        """返回 schema 默认值（models 模型路径保留当前，单一来源派生）。"""
        ocr = self._cm.ocr()
        d = ocr_defaults_update()
        model = cast(dict[str, object], d["model"])
        device = cast(dict[str, object], d["device"])
        thresholds = cast(dict[str, object], d["thresholds"])
        return {
            "mode": model["mode"],
            "default_spec": model["default_spec"],
            "gpu_enabled": device["gpu_enabled"],
            "text_score": thresholds["text_score"],
            "box_thresh": thresholds["box_thresh"],
            "unclip_ratio": thresholds["unclip_ratio"],
            "language": d["language"],
            "models": self._models_dict(ocr.model.models),
        }

    def restore_defaults(self) -> None:
        """写回 schema 默认值（models 模型路径保留当前）。"""
        self._cm.save_ocr(self.build_update(self.defaults()))
