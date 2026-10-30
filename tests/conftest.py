"""pytest 共享 fixture 与最小配置样例。"""

import pytest

from config.manager import ConfigManager

MINIMAL_CONFIG_YAML = """\
ocr:
  model:
    mode: small
    default_spec: small
    models:
      tiny:
        det: t/det.onnx
        rec: t/rec.onnx
        dict_path: t/dict.txt
        cls: t/cls.onnx
      small:
        det: s/det.onnx
        rec: s/rec.onnx
        dict_path: s/dict.txt
        cls: s/cls.onnx
      medium:
        det: m/det.onnx
        rec: m/rec.onnx
        dict_path: m/dict.txt
        cls: m/cls.onnx
  thresholds:
    text_score: 0.5
    box_thresh: 0.5
    unclip_ratio: 1.6
  language: zh
"""


@pytest.fixture
def config_manager(tmp_path):
    """构造指向临时最小 config.yaml 的 ConfigManager。"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(MINIMAL_CONFIG_YAML, encoding="utf-8")
    return ConfigManager(cfg)
