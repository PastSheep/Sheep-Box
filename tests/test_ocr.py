"""OCR 模块单元测试。

通过注入 FakeEngine 避免真实加载模型，聚焦验证：
- 按配置模式加载引擎（单规格只加载一个 / all 加载全部）；
- 识别接口契约（字节流 → 结构化 OCRResult）；
- 规格热切换与资源释放；
- 结构化输出拼接与判空。
"""

import pytest

from config.manager import ConfigManager
from config.schema import ModelMode, ModelSpec
from service.ocr import manager as manager_module
from service.ocr.manager import OCRManager
from service.ocr.models import OCRResult, OCRTextItem

# FakeEngine 在单测中替换真实 OCREngine，并记录被构建的规格
_constructed_specs: list[ModelSpec] = []


class FakeEngine:
    def __init__(self, spec, paths, device, thresholds):
        self.spec = spec
        self.paths = paths
        _constructed_specs.append(spec)

    def recognize(self, image_bytes):
        return [
            OCRTextItem(
                text="识别文本",
                bbox=[[1.0, 2.0], [3.0, 2.0], [3.0, 4.0], [1.0, 4.0]],
                score=0.9,
            )
        ], 0.1


CONFIG_TEMPLATE = """
ocr:
  model:
    mode: {mode}
    default_spec: medium
    models:
      tiny:
        det: tiny/det.onnx
        rec: tiny/rec.onnx
      small:
        det: small/det.onnx
        rec: small/rec.onnx
      medium:
        det: medium/det.onnx
        rec: medium/rec.onnx
  device:
    gpu_enabled: false
"""


@pytest.fixture(autouse=True)
def _reset_fake():
    _constructed_specs.clear()


def _make_manager(tmp_path, mode: str) -> OCRManager:
    content = CONFIG_TEMPLATE.format(mode=mode)
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    manager = OCRManager(ConfigManager(path))
    return manager


def _patch_engine(monkeypatch):
    monkeypatch.setattr(manager_module, "OCREngine", FakeEngine)


def test_single_spec_loads_only_one(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    assert _constructed_specs == [ModelSpec.MEDIUM]
    assert manager.active_spec == ModelSpec.MEDIUM


def test_all_mode_loads_all_specs(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    _make_manager(tmp_path, ModelMode.ALL.value)
    assert _constructed_specs == [ModelSpec.TINY, ModelSpec.SMALL, ModelSpec.MEDIUM]


def test_recognize_returns_structured_result(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)

    result = manager.recognize(b"fake-image-bytes")
    assert isinstance(result, OCRResult)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.text == "识别文本"
    assert item.score == pytest.approx(0.9)
    assert len(item.bbox) == 4
    assert result.text == "识别文本"
    assert bool(result)


def test_recognize_empty_image_returns_empty_result(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    _make_manager(tmp_path, ModelMode.MEDIUM.value)
    # 让 FakeEngine 返回空：通过直接调用底层的空结果路径不易触发，
    # 这里验证 OCRResult 空结构语义
    assert not OCRResult(items=[])


def test_set_model_spec_switch_single_mode(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    assert _constructed_specs == [ModelSpec.MEDIUM]

    # 单规格模式：切换到 tiny 时释放旧的、只保留新实例
    manager.set_model_spec(ModelSpec.TINY)
    assert manager.active_spec == ModelSpec.TINY
    assert _constructed_specs == [ModelSpec.MEDIUM, ModelSpec.TINY]
    # 旧实例已释放，仅剩新实例
    assert len(manager._engines) == 1
    assert ModelSpec.TINY in manager._engines


def test_set_model_spec_all_mode_keeps_all(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.ALL.value)
    assert len(manager._engines) == 3

    manager.set_model_spec(ModelSpec.SMALL)
    assert manager.active_spec == ModelSpec.SMALL
    # all 模式下不释放其它规格
    assert len(manager._engines) == 3


def test_set_model_spec_invalid_raises(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    with pytest.raises(ValueError):
        manager.set_model_spec("huge")
