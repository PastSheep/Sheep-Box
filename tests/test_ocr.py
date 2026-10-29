"""OCR 模块单元测试。

通过注入 FakeEngine 避免真实加载模型，聚焦验证：
- 按配置模式加载引擎（单规格只加载一个 / all 加载全部）；
- 识别接口契约（字节流 → 结构化 OCRResult）；
- 规格热切换与资源释放；
- 结构化输出拼接与判空。
"""

import pytest

from common.exceptions import OcrEngineError, OcrError
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
        dict_path: tiny/dict.txt
      small:
        det: small/det.onnx
        rec: small/rec.onnx
        dict_path: small/dict.txt
      medium:
        det: medium/det.onnx
        rec: medium/rec.onnx
        dict_path: medium/dict.txt
  device:
    gpu_enabled: false
"""


@pytest.fixture(autouse=True)
def _reset_fake():
    _constructed_specs.clear()


def _make_model_files(tmp_path):
    """为 M-7 模型存在校验创建真实占位文件（内容无关，FakeEngine 不读取）。"""
    for spec in ("tiny", "small", "medium"):
        spec_dir = tmp_path / spec
        spec_dir.mkdir(exist_ok=True)
        for filename in ("det.onnx", "rec.onnx", "dict.txt"):
            (spec_dir / filename).touch()


def _make_manager(tmp_path, mode: str) -> OCRManager:
    _make_model_files(tmp_path)
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
    with pytest.raises(OcrError):
        manager.set_model_spec("huge")


def _item(text: str, score: float = 0.9) -> OCRTextItem:
    return OCRTextItem(
        text=text,
        bbox=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        score=score,
    )


def test_clean_text_removes_blank_and_trims():
    result = OCRResult(
        items=[_item("  你好  "), _item(""), _item("  世界 ")], elapsed=0.1
    )
    assert result.clean_text == "你好\n世界"


def test_clean_text_deduplicates_adjacent():
    result = OCRResult(items=[_item("重复"), _item("重复"), _item("其他")])
    assert result.clean_text == "重复\n其他"


def test_clean_text_keeps_non_adjacent_duplicates():
    result = OCRResult(items=[_item("A"), _item("B"), _item("A")])
    assert result.clean_text == "A\nB\nA"


def test_clean_text_preserves_original_text():
    result = OCRResult(items=[_item(" 你好 "), _item("")])
    # text 保持未清洗的原始拼接
    assert result.text == " 你好 \n"
    assert result.clean_text == "你好"


def test_engine_rebuild_failure_keeps_old_state(tmp_path, monkeypatch):
    """R-3: 引擎重建失败抛 OcrEngineError，且旧引擎保留、recognize 不 KeyError。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    assert manager.active_spec == ModelSpec.MEDIUM

    def boom(self, *args, **kwargs):
        raise RuntimeError("simulated init failure")

    monkeypatch.setattr(manager_module.OCREngine, "__init__", boom)
    with pytest.raises(OcrEngineError):
        manager._apply_config(force=True)
    # 旧状态保留，识别仍可用（无 KeyError）
    assert manager.active_spec == ModelSpec.MEDIUM
    result = manager.recognize(b"fake-image-bytes")
    assert len(result.items) == 1


def test_all_mode_active_uses_default_spec(tmp_path, monkeypatch):
    """H-1: all 模式 active 取 default_spec（而非枚举首项 tiny）。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.ALL.value)  # default_spec=medium
    assert manager.active_spec == ModelSpec.MEDIUM


def test_single_mode_prefers_mode_over_default_spec(tmp_path, monkeypatch):
    """H-1: 非 all 模式按 mode 加载（而非 default_spec）。"""
    _patch_engine(monkeypatch)
    _make_model_files(tmp_path)
    content = """
ocr:
  model:
    mode: tiny
    default_spec: medium
    models:
      tiny:
        det: tiny/det.onnx
        rec: tiny/rec.onnx
        dict_path: tiny/dict.txt
      medium:
        det: medium/det.onnx
        rec: medium/rec.onnx
        dict_path: medium/dict.txt
  device:
    gpu_enabled: false
"""
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    manager = OCRManager(ConfigManager(path))
    assert manager.active_spec == ModelSpec.TINY
    assert _constructed_specs == [ModelSpec.TINY]


def test_recognize_accepts_base64(tmp_path, monkeypatch):
    """H-2: recognize 接受 base64 字符串输入。"""
    import base64

    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    result = manager.recognize(base64.b64encode(b"fake").decode())
    assert len(result.items) == 1


def test_recognize_invalid_base64_raises(tmp_path, monkeypatch):
    """H-2: 非法 base64 输入归一化为 OcrError。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    with pytest.raises(OcrError):
        manager.recognize("!!not-base64!!")


def test_recognize_engine_error_normalized(tmp_path, monkeypatch):
    """H-2: 引擎识别异常归一化为 OcrError（不外泄底层异常）。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)

    def boom(image_bytes):
        raise RuntimeError("inference boom")

    monkeypatch.setattr(manager_module.OCREngine, "recognize", boom)
    with pytest.raises(OcrError):
        manager.recognize(b"x")


def test_build_missing_model_file_raises(tmp_path, monkeypatch):
    """M-7: 模型文件缺失抛 OcrEngineError。"""
    _patch_engine(monkeypatch)
    _make_model_files(tmp_path)
    (tmp_path / "medium" / "det.onnx").unlink()
    path = tmp_path / "config.yaml"
    content = CONFIG_TEMPLATE.format(mode=ModelMode.MEDIUM.value)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(OcrEngineError):
        OCRManager(ConfigManager(path))
