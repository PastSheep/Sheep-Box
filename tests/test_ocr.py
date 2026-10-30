"""OCR 模块单元测试。

通过注入 FakeEngine 避免真实加载模型，聚焦验证：
- 按配置模式加载引擎（单规格只加载一个 / all 加载全部）；
- 识别接口契约（字节流 / base64 → 结构化 OCRResult）；
- 规格热切换与资源释放（close / 上下文管理）；
- 引擎重建失败回滚、GPU 回退 CPU、模型文件存在校验；
- 结构化输出拼接与判空。
"""

import base64
from typing import Any, cast

import pytest

from common.exceptions import OcrEngineError, OcrError
from config.manager import ConfigManager
from config.schema import ModelMode, ModelSpec, ModelSpecPaths, OcrThresholdConfig
from service.ocr import engine as engine_module
from service.ocr import manager as manager_module
from service.ocr.device import DevicePlan
from service.ocr.manager import OCRManager
from service.ocr.models import OCRResult, OCRTextItem

# FakeEngine 在单测中替换真实 OCREngine，并记录被构建的规格
_constructed_specs: list[ModelSpec] = []
_recognized_images: list[bytes] = []
_closed_specs: list[ModelSpec] = []


class FakeEngine:
    def __init__(self, spec, paths, device, thresholds):
        self.spec = spec
        self.paths = paths
        self.device = device
        self.thresholds = thresholds
        _constructed_specs.append(spec)

    def recognize(self, image_bytes):
        _recognized_images.append(image_bytes)
        return [
            OCRTextItem(
                text="识别文本",
                bbox=[[1.0, 2.0], [3.0, 2.0], [3.0, 4.0], [1.0, 4.0]],
                score=0.9,
            )
        ], 0.1

    def close(self) -> None:
        _closed_specs.append(self.spec)


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
"""


@pytest.fixture(autouse=True)
def _reset_fake():
    _constructed_specs.clear()
    _recognized_images.clear()
    _closed_specs.clear()


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
    """识别返回空结果时 OCRResult 保持空语义（真实调用 recognize）。"""

    class EmptyEngine(FakeEngine):
        def recognize(self, image_bytes):
            _recognized_images.append(image_bytes)
            return [], 0.2

    monkeypatch.setattr(manager_module, "OCREngine", EmptyEngine)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    result = manager.recognize(b"fake-image-bytes")
    assert result.items == []
    assert result.text == ""
    assert result.elapsed == pytest.approx(0.2)
    assert not result


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
      small:
        det: small/det.onnx
        rec: small/rec.onnx
        dict_path: small/dict.txt
      medium:
        det: medium/det.onnx
        rec: medium/rec.onnx
        dict_path: medium/dict.txt
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


def test_recognize_accepts_data_uri_and_whitespace(tmp_path, monkeypatch):
    """H-2: base64 兼容 data URI 前缀与空白字符，解码后字节原样交给引擎。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    encoded = base64.b64encode(b"fake-image").decode()
    spaced = f"data:image/png;base64, {encoded[:4]}\n{encoded[4:]} "
    manager.recognize(spaced)
    assert _recognized_images[-1] == b"fake-image"


def test_recognize_empty_bytes_raises(tmp_path, monkeypatch):
    """H-2: 空 bytes 快速失败为 OcrError。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    with pytest.raises(OcrError, match="图片输入为空"):
        manager.recognize(b"")


def test_recognize_unsupported_type_raises(tmp_path, monkeypatch):
    """H-2: 不支持的类型归一化为 OcrError。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    with pytest.raises(OcrError, match="不支持的图片输入类型"):
        manager.recognize(cast(Any, 123))


def test_close_releases_engines_and_prevents_recognize(tmp_path, monkeypatch):
    """M-10: close 释放引擎；关闭后 recognize 抛 OcrError 而非隐式重建。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    manager.close()
    assert _closed_specs == [ModelSpec.MEDIUM]
    with pytest.raises(OcrError, match="OCR 引擎未加载"):
        manager.recognize(b"x")
    # 重复 close 安全
    manager.close()


def test_context_manager_closes_engine(tmp_path, monkeypatch):
    """M-10: with 退出时自动 close。"""
    _patch_engine(monkeypatch)
    with _make_manager(tmp_path, ModelMode.MEDIUM.value) as manager:
        assert manager.recognize(b"x").items
    assert _closed_specs == [ModelSpec.MEDIUM]


def test_default_spec_hot_update_in_all_mode(tmp_path, monkeypatch):
    """H-1: all 模式下 default_spec 变更触发热重建并切换 active。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.ALL.value)  # default_spec=medium
    assert manager.active_spec == ModelSpec.MEDIUM
    cfg_path = tmp_path / "config.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    cfg_path.write_text(
        text.replace("default_spec: medium", "default_spec: small"),
        encoding="utf-8",
    )
    manager.recognize(b"x")
    assert manager.active_spec == ModelSpec.SMALL


def test_threshold_hot_update_rebuilds_engine(tmp_path, monkeypatch):
    """H-4: 阈值变更触发引擎重建，新阈值进入引擎参数。"""
    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    engine = cast(FakeEngine, manager._engines[ModelSpec.MEDIUM])
    assert engine.thresholds.text_score == 0.5
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "  thresholds:\n    text_score: 0.9\n",
        encoding="utf-8",
    )
    manager.recognize(b"x")
    engine = cast(FakeEngine, manager._engines[ModelSpec.MEDIUM])
    assert engine.thresholds.text_score == 0.9


def test_set_model_spec_failure_keeps_old_engine(tmp_path, monkeypatch):
    """R-3: 切换规格构建失败时旧引擎与 active 保持不变。"""

    class BoomTinyEngine(FakeEngine):
        def __init__(self, spec, paths, device, thresholds):
            if spec == ModelSpec.TINY:
                raise RuntimeError("simulated tiny init failure")
            super().__init__(spec, paths, device, thresholds)

    _patch_engine(monkeypatch)
    manager = _make_manager(tmp_path, ModelMode.MEDIUM.value)
    monkeypatch.setattr(manager_module, "OCREngine", BoomTinyEngine)
    with pytest.raises(OcrEngineError):
        manager.set_model_spec("tiny")
    assert manager.active_spec == ModelSpec.MEDIUM
    assert manager.recognize(b"x").items


def _model_paths(tmp_path) -> ModelSpecPaths:
    for filename in ("det.onnx", "rec.onnx", "dict.txt"):
        (tmp_path / filename).touch()
    return ModelSpecPaths(
        det=str(tmp_path / "det.onnx"),
        rec=str(tmp_path / "rec.onnx"),
        dict_path=str(tmp_path / "dict.txt"),
    )


def test_engine_gpu_init_failure_falls_back_to_cpu(tmp_path, monkeypatch):
    """M: GPU 初始化失败自动用 CPU 参数重试一次（引擎层）。"""
    paths = _model_paths(tmp_path)
    calls: list[dict[str, Any]] = []

    class FakeRapidOCR:
        def __init__(self, params=None):
            calls.append(dict(params or {}))
            if (params or {}).get("EngineConfig.onnxruntime.use_dml"):
                raise RuntimeError("dml init failure")

    monkeypatch.setattr(engine_module, "RapidOCR", FakeRapidOCR)
    engine = engine_module.OCREngine(
        spec=ModelSpec.TINY,
        paths=paths,
        device=DevicePlan(use_dml=True, device_name="directml"),
        thresholds=OcrThresholdConfig(),
    )
    assert len(calls) == 2
    assert "EngineConfig.onnxruntime.use_dml" not in calls[1]
    assert engine.spec == ModelSpec.TINY


def test_engine_missing_model_does_not_retry_gpu(tmp_path, monkeypatch):
    """M: 模型文件缺失属部署问题，不得被当作 GPU 失败触发 CPU 重试。"""
    calls: list[dict[str, Any]] = []

    class FakeRapidOCR:
        def __init__(self, params=None):
            calls.append(dict(params or {}))

    monkeypatch.setattr(engine_module, "RapidOCR", FakeRapidOCR)
    missing = ModelSpecPaths(
        det=str(tmp_path / "missing-det.onnx"),
        rec=str(tmp_path / "missing-rec.onnx"),
        dict_path=str(tmp_path / "missing-dict.txt"),
    )
    with pytest.raises(OcrEngineError, match="模型文件不存在"):
        engine_module.OCREngine(
            spec=ModelSpec.TINY,
            paths=missing,
            device=DevicePlan(use_dml=True, device_name="directml"),
            thresholds=OcrThresholdConfig(),
        )
    assert calls == []
