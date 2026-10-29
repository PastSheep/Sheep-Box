"""通用配置中心单元测试。

覆盖：YAML 加载、必填严格校验、可选回退、非法枚举、文件缺失、运行时热更新。
"""

import pytest

from common.exceptions import ConfigError
from config.loader import load_config
from config.manager import ConfigManager

VALID_YAML = """
ocr:
  model:
    mode: medium
    default_spec: medium
    models:
      medium:
        det: assets/ocr/models/medium/det.onnx
        rec: assets/ocr/models/medium/rec.onnx
        dict_path: assets/ocr/models/medium/dict.txt
        cls: assets/ocr/models/medium/cls.onnx
  device:
    gpu_enabled: false
"""


def _write(tmp_path, content: str):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path):
    path = _write(tmp_path, VALID_YAML)
    cfg = load_config(path)
    assert cfg.ocr.model.mode.value == "medium"
    assert cfg.ocr.model.default_spec.value == "medium"
    assert cfg.ocr.device.gpu_enabled is False
    assert cfg.ocr.language == "zh"


def test_missing_ocr_section_raises(tmp_path):
    path = _write(tmp_path, "other: 1\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_required_models_raises(tmp_path):
    content = "ocr:\n  model:\n    mode: medium\n"
    path = _write(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_required_model_path_raises(tmp_path):
    content = """
ocr:
  model:
    models:
      medium:
        rec: b.onnx
"""
    path = _write(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_invalid_mode_enum_raises(tmp_path):
    content = VALID_YAML.replace("mode: medium", "mode: huge")
    path = _write(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_invalid_top_level_type_raises(tmp_path):
    path = _write(tmp_path, "- a\n- b\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_optional_fields_use_defaults(tmp_path):
    content = """
ocr:
  model:
    models:
      small:
        det: a.onnx
        rec: b.onnx
        dict_path: d.txt
"""
    path = _write(tmp_path, content)
    cfg = load_config(path)
    # 未提供 device / thresholds / mode，均回退默认值
    assert cfg.ocr.device.gpu_enabled is True  # 首版默认启用 GPU
    assert cfg.ocr.thresholds.text_score == 0.5
    assert cfg.ocr.model.mode.value == "small"  # 默认规格为 small
    assert cfg.ocr.model.default_spec.value == "small"
    assert cfg.ocr.language == "zh"


def test_missing_file_raises():
    with pytest.raises(ConfigError):
        load_config("E:/no/such/config.yaml")


def test_hot_reload_on_change(tmp_path):
    path = _write(tmp_path, VALID_YAML)
    manager = ConfigManager(path)
    assert manager.ocr().device.gpu_enabled is False

    # 修改配置并强制更新时间戳
    updated = VALID_YAML.replace("gpu_enabled: false", "gpu_enabled: true")
    _write(tmp_path, updated)
    # 访问时自动检测变更并热更新
    assert manager.ocr().device.gpu_enabled is True


def test_save_ocr_yaml_12_semantics(tmp_path):
    """R-1: yes 等 YAML 1.1 布尔词写回后保持字符串（ruamel 1.2 读写一致）。"""
    content = """
ocr:
  model:
    mode: medium
    default_spec: medium
    models:
      medium:
        det: a.onnx
        rec: b.onnx
        dict_path: d.txt
"""
    path = _write(tmp_path, content)
    cm = ConfigManager(path)
    cm.save_ocr({"language": "yes"})
    # 写回后应能正确读回：language 为字符串 'yes'，而非 YAML 1.1 的 True
    assert cm.ocr().language == "yes"


def test_save_ocr_unknown_key_rejected_file_untouched(tmp_path):
    """R-2: 未知键被 extra=forbid 拒绝，且文件不被污染。"""
    path = _write(tmp_path, VALID_YAML)
    before = path.read_text(encoding="utf-8")
    cm = ConfigManager(path)
    with pytest.raises(ConfigError):
        cm.save_ocr({"foo": "bar"})
    assert path.read_text(encoding="utf-8") == before
