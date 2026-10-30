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
      tiny:
        det: assets/ocr/models/tiny/det.onnx
        rec: assets/ocr/models/tiny/rec.onnx
        dict_path: assets/ocr/models/tiny/dict.txt
      small:
        det: assets/ocr/models/small/det.onnx
        rec: assets/ocr/models/small/rec.onnx
        dict_path: assets/ocr/models/small/dict.txt
      medium:
        det: assets/ocr/models/medium/det.onnx
        rec: assets/ocr/models/medium/rec.onnx
        dict_path: assets/ocr/models/medium/dict.txt
        cls: assets/ocr/models/medium/cls.onnx
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
    assert cfg.ocr.language == "zh"


def test_app_section_defaults_when_absent(tmp_path):
    """app 段可选：缺省回退 ui_language=zh_CN（程序偏好默认）。"""
    path = _write(tmp_path, VALID_YAML)
    cfg = load_config(path)
    assert cfg.app.ui_language == "zh_CN"


def test_app_ui_language_override(tmp_path):
    """提供 app.ui_language 时生效（界面语言可配置）。"""
    content = VALID_YAML + "\napp:\n  ui_language: en_US\n"
    path = _write(tmp_path, content)
    cfg = load_config(path)
    assert cfg.app.ui_language == "en_US"


def test_app_unknown_key_rejected(tmp_path):
    """app 段未知键（extra=forbid）直接拒绝。"""
    content = VALID_YAML + "\napp:\n  theme: dark\n"
    path = _write(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


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
      tiny:
        det: t.onnx
        rec: t.onnx
        dict_path: t.txt
      small:
        det: a.onnx
        rec: b.onnx
        dict_path: d.txt
      medium:
        det: m.onnx
        rec: m.onnx
        dict_path: m.txt
"""
    path = _write(tmp_path, content)
    cfg = load_config(path)
    # 未提供 thresholds / mode，均回退默认值
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
    assert manager.ocr().model.mode.value == "medium"

    # 修改配置并强制更新时间戳
    updated = VALID_YAML.replace("mode: medium", "mode: tiny")
    _write(tmp_path, updated)
    # 访问时自动检测变更并热更新
    assert manager.ocr().model.mode.value == "tiny"


def test_save_ocr_yaml_12_semantics(tmp_path):
    """R-1: yes 等 YAML 1.1 布尔词写回后保持字符串（ruamel 1.2 读写一致）。"""
    content = """
ocr:
  model:
    mode: medium
    default_spec: medium
    models:
      tiny:
        det: t/det.onnx
        rec: t/rec.onnx
        dict_path: t/dict.txt
      small:
        det: s/det.onnx
        rec: s/rec.onnx
        dict_path: s/dict.txt
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


def test_schema_rejects_unknown_top_level_key(tmp_path):
    """H-6: 顶层未知键（AppConfig extra=forbid）直接拒绝。"""
    path = _write(tmp_path, VALID_YAML.replace("ocr:", "unknown_section: 1\nocr:"))
    with pytest.raises(ConfigError):
        load_config(path)


def test_schema_rejects_out_of_range_threshold(tmp_path):
    """H-6: 阈值超出合法范围（text_score>1 / unclip_ratio<=0）被拒绝。"""
    content = VALID_YAML + "\n  thresholds:\n    text_score: 1.5\n    unclip_ratio: 0\n"
    path = _write(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_schema_requires_all_model_specs(tmp_path):
    """H-6: models 必须覆盖 tiny/small/medium 三档，缺失档位报错。"""
    content = """
ocr:
  model:
    mode: medium
    models:
      medium:
        det: m.onnx
        rec: m.onnx
        dict_path: m.txt
"""
    path = _write(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_save_ocr_atomic_write_creates_backup(tmp_path):
    """H-4: 原子写成功路径——.bak 为旧内容、无残留 .tmp、新值生效。"""
    path = _write(tmp_path, VALID_YAML)
    before = path.read_bytes()
    cm = ConfigManager(path)
    cm.save_ocr({"model": {"mode": "tiny"}})
    bak = path.with_suffix(path.suffix + ".bak")
    assert bak.read_bytes() == before
    assert not path.with_suffix(path.suffix + ".tmp").exists()
    assert cm.ocr().model.mode.value == "tiny"


def test_save_ocr_invalid_value_leaves_file_and_no_temp(tmp_path):
    """H-4/H-6: 非法值写回失败时原文件字节不变、无 .tmp/.bak 残留。"""
    path = _write(tmp_path, VALID_YAML)
    before = path.read_bytes()
    cm = ConfigManager(path)
    with pytest.raises(ConfigError):
        cm.save_ocr({"thresholds": {"text_score": 2.0}})
    assert path.read_bytes() == before
    assert not path.with_suffix(path.suffix + ".tmp").exists()
    assert not path.with_suffix(path.suffix + ".bak").exists()
