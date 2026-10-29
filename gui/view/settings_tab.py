"""设置标签页：OCR 配置的可视化编辑表单。

提供"保存并重载"（写回 config.yaml 并触发配置中心热更新）与
"恢复默认值"（写回 schema 默认）两个操作。
"""

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.schema import ModelMode, ModelSpec
from gui.controller.settings_controller import SettingsController

logger = logging.getLogger(__name__)

__all__ = ["SettingsTab"]


class SettingsTab(QWidget):
    """设置标签页：查看 / 编辑 OCR 配置并保存（联动配置中心热更新）。"""

    def __init__(
        self, controller: SettingsController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._mode_combo: QComboBox
        self._default_spec_combo: QComboBox
        self._gpu_check: QCheckBox
        self._text_score: QDoubleSpinBox
        self._box_thresh: QDoubleSpinBox
        self._unclip_ratio: QDoubleSpinBox
        self._language_edit: QLineEdit
        self._models_label: QLabel
        self._status_label: QLabel
        self._build_ui()
        self.reload_from_config()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._mode_combo = QComboBox()
        self._mode_combo.addItems([m.value for m in ModelMode])
        form.addRow("模型模式", self._mode_combo)

        self._default_spec_combo = QComboBox()
        self._default_spec_combo.addItems([m.value for m in ModelSpec])
        form.addRow("默认规格", self._default_spec_combo)

        self._gpu_check = QCheckBox("启用 GPU 加速（探测失败自动回退 CPU）")
        form.addRow("设备", self._gpu_check)

        self._text_score = self._make_double_spin(0.0, 1.0, 0.05)
        form.addRow("文本置信度阈值", self._text_score)
        self._box_thresh = self._make_double_spin(0.0, 1.0, 0.05)
        form.addRow("检测框阈值", self._box_thresh)
        self._unclip_ratio = self._make_double_spin(0.1, 3.0, 0.1)
        form.addRow("检测框扩张比例", self._unclip_ratio)

        self._language_edit = QLineEdit()
        form.addRow("识别语言", self._language_edit)

        self._models_label = QLabel()
        self._models_label.setWordWrap(True)
        form.addRow("模型路径（只读）", self._models_label)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self._save_btn = QPushButton("保存并重载")
        self._save_btn.clicked.connect(self._on_save)
        self._restore_btn = QPushButton("恢复默认值")
        self._restore_btn.clicked.connect(self._on_restore)
        button_row.addStretch(1)
        button_row.addWidget(self._restore_btn)
        button_row.addWidget(self._save_btn)
        layout.addLayout(button_row)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

    @staticmethod
    def _make_double_spin(
        minimum: float, maximum: float, step: float
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        return spin

    @staticmethod
    def _to_float(value: object) -> float:
        """把表单数值安全转 ``float``（配置中心返回的数值型字段）。"""
        return float(value) if isinstance(value, (int, float)) else 0.0

    def reload_from_config(self) -> None:
        """从配置中心读取当前值并回填表单。"""
        values = self._controller.load()
        self._mode_combo.setCurrentText(str(values["mode"]))
        self._default_spec_combo.setCurrentText(str(values["default_spec"]))
        self._gpu_check.setChecked(bool(values["gpu_enabled"]))
        self._text_score.setValue(self._to_float(values["text_score"]))
        self._box_thresh.setValue(self._to_float(values["box_thresh"]))
        self._unclip_ratio.setValue(self._to_float(values["unclip_ratio"]))
        self._language_edit.setText(str(values["language"]))
        models = values.get("models")
        if isinstance(models, dict):
            self._models_label.setText(self._format_models(models))

    def _collect(self) -> dict[str, object]:
        """收集当前表单值。"""
        return {
            "mode": self._mode_combo.currentText(),
            "default_spec": self._default_spec_combo.currentText(),
            "gpu_enabled": self._gpu_check.isChecked(),
            "text_score": self._text_score.value(),
            "box_thresh": self._box_thresh.value(),
            "unclip_ratio": self._unclip_ratio.value(),
            "language": self._language_edit.text(),
        }

    @staticmethod
    def _format_models(models: dict[str, object]) -> str:
        """把各规格模型路径格式化为多行只读文本。"""
        lines: list[str] = []
        for spec, paths in models.items():
            if isinstance(paths, dict):
                lines.append(
                    f"[{spec}] det={paths.get('det')} rec={paths.get('rec')} "
                    f"dict={paths.get('dict_path')} cls={paths.get('cls')}"
                )
        return "\n".join(lines)

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status_label.setText(text)
        if error:
            self._status_label.setStyleSheet("color:#b91c1c;")
        else:
            self._status_label.setStyleSheet("color:#15803d;")

    def _on_save(self) -> None:
        values = self._collect()
        try:
            self._controller.save(values)
        except Exception as exc:
            logger.exception("保存配置失败")
            self._set_status(f"保存失败: {exc}", error=True)
            return
        self.reload_from_config()  # 从配置中心回读，展示实际生效值
        self._set_status("已保存并重载，配置中心热更新生效")

    def _on_restore(self) -> None:
        try:
            self._controller.restore_defaults()
        except Exception as exc:
            logger.exception("恢复默认值失败")
            self._set_status(f"恢复默认失败: {exc}", error=True)
            return
        self.reload_from_config()
        self._set_status("已恢复默认值并重载")
