"""CLI 命令单元测试。

config 命令通过 ``--config`` 注入临时配置，不触碰真实 config.yaml；
ocr 命令 mock ``OCRManager``，验证参数解析与文本/JSON 输出格式。
"""

import json

from typer.testing import CliRunner

from cli.app import app
from common.exceptions import OcrError
from config.defaults import ocr_defaults_update
from config.manager import ConfigManager
from config.schema import ModelSpec
from service.ocr.models import OCRResult, OCRTextItem

runner = CliRunner()


def _fake_ocr_result() -> OCRResult:
    return OCRResult(
        items=[
            OCRTextItem(
                text="你好",
                bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
                score=0.99,
            ),
            OCRTextItem(
                text="",
                bbox=[[2, 0], [3, 0], [3, 1], [2, 1]],
                score=0.8,
            ),
        ],
        elapsed=0.1,
    )


class FakeOCRManager:
    """替代 OCRManager，记录构造的配置并返回固定识别结果。"""

    def __init__(self, cm: object) -> None:
        self.active_spec = ModelSpec.SMALL
        self.closed = False
        self.fail_with: Exception | None = None

    def set_model_spec(self, spec: ModelSpec) -> None:
        self.active_spec = ModelSpec(spec)

    def recognize(self, image_bytes: bytes) -> OCRResult:
        if self.fail_with is not None:
            raise self.fail_with
        return _fake_ocr_result()

    def close(self) -> None:
        self.closed = True


def _patch_ocr_manager(monkeypatch, manager: FakeOCRManager) -> None:
    monkeypatch.setattr("cli.commands.ocr.build_ocr_manager", lambda cfg: manager)


# ---- config 命令 ----


def test_config_get_whole(config_manager):
    result = runner.invoke(app, ["config", "get", "--config", str(config_manager.path)])
    assert result.exit_code == 0
    assert "mode: small" in result.stdout
    assert "gpu_enabled: True" in result.stdout


def test_config_get_path(config_manager):
    result = runner.invoke(
        app,
        ["config", "get", "device.gpu_enabled", "--config", str(config_manager.path)],
    )
    assert result.exit_code == 0
    assert "device.gpu_enabled: True" in result.stdout


def test_config_get_json(config_manager):
    result = runner.invoke(
        app,
        ["config", "get", "model.mode", "--json", "--config", str(config_manager.path)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["model.mode"] == "small"


def test_config_list(config_manager):
    result = runner.invoke(
        app, ["config", "list", "--config", str(config_manager.path)]
    )
    assert result.exit_code == 0
    assert "mode: small" in result.stdout


def test_config_set_updates_yaml(config_manager):
    result = runner.invoke(
        app,
        ["config", "set", "model.mode", "tiny", "--config", str(config_manager.path)],
    )
    assert result.exit_code == 0
    assert "已更新" in result.stdout
    cm = ConfigManager(config_manager.path)
    assert cm.ocr().model.mode.value == "tiny"


def test_config_set_parses_types(config_manager):
    runner.invoke(
        app,
        [
            "config",
            "set",
            "device.gpu_enabled",
            "false",
            "--config",
            str(config_manager.path),
        ],
    )
    cm = ConfigManager(config_manager.path)
    assert cm.ocr().device.gpu_enabled is False


def test_config_set_invalid_rejected(config_manager):
    result = runner.invoke(
        app,
        ["config", "set", "model.mode", "huge", "--config", str(config_manager.path)],
    )
    assert result.exit_code != 0


def test_config_reset(config_manager):
    runner.invoke(
        app,
        ["config", "set", "model.mode", "all", "--config", str(config_manager.path)],
    )
    result = runner.invoke(
        app, ["config", "reset", "--config", str(config_manager.path)]
    )
    assert result.exit_code == 0
    assert "已恢复默认值" in result.stdout
    cm = ConfigManager(config_manager.path)
    assert cm.ocr().model.mode.value == "small"
    assert cm.ocr().device.gpu_enabled is True


def test_config_get_missing_path_exit_2(config_manager):
    """R-2: config get 路径不存在 → 退出码 2 + 明确错误。"""
    result = runner.invoke(
        app,
        ["config", "get", "no.such.path", "--config", str(config_manager.path)],
    )
    assert result.exit_code == 2
    assert "配置项不存在" in result.output


def test_config_get_null_value_not_treated_as_missing(tmp_path):
    """R-2: 合法的 None 值（如未配置 cls）应输出 null 而非「路径不存在」。"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
ocr:
  model:
    mode: small
    default_spec: small
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
        det: m/det.onnx
        rec: m/rec.onnx
        dict_path: m/dict.txt
""",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["config", "get", "model.models.tiny.cls", "--json", "--config", str(cfg)],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["model.models.tiny.cls"] is None


def test_config_set_ocr_prefix_rejected_file_unchanged(config_manager):
    """R-2: 帮助统一为相对 ocr 段；带 ocr. 前缀的路径被拒绝且不写文件。"""
    before = config_manager.path.read_bytes()
    result = runner.invoke(
        app,
        [
            "config",
            "set",
            "ocr.model.mode",
            "medium",
            "--config",
            str(config_manager.path),
        ],
    )
    assert result.exit_code == 2
    assert "配置项不存在" in result.output
    assert config_manager.path.read_bytes() == before


def test_config_set_unknown_key_rejected_file_unchanged(config_manager):
    """R-2/H-6: 未知键在写回前被拒绝，配置文件字节不变。"""
    before = config_manager.path.read_bytes()
    result = runner.invoke(
        app, ["config", "set", "foo", "bar", "--config", str(config_manager.path)]
    )
    assert result.exit_code == 2
    assert config_manager.path.read_bytes() == before


def test_config_set_invalid_enum_exit_2(config_manager):
    """R-2/H-6: 非法枚举值 → 退出码 2 + 友好错误（不泄露 traceback）。"""
    result = runner.invoke(
        app,
        [
            "config",
            "set",
            "model.mode",
            "huge",
            "--config",
            str(config_manager.path),
        ],
    )
    assert result.exit_code == 2
    assert "配置写入失败" in result.output


def test_config_get_bad_yaml_exit_2(tmp_path):
    """R-2: 配置无效时 config get 返回退出码 2，而非 traceback。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text("ocr: [unclosed\n", encoding="utf-8")
    result = runner.invoke(app, ["config", "get", "--config", str(bad)])
    assert result.exit_code == 2
    assert "配置读取失败" in result.output


def test_config_reset_uses_single_source_defaults(config_manager):
    """M: reset 写回值来自 config.defaults.ocr_defaults_update（单一来源）。"""
    runner.invoke(
        app,
        ["config", "set", "model.mode", "all", "--config", str(config_manager.path)],
    )
    result = runner.invoke(
        app, ["config", "reset", "--config", str(config_manager.path)]
    )
    assert result.exit_code == 0
    cm = ConfigManager(config_manager.path)
    defaults = ocr_defaults_update()
    assert cm.ocr().model.mode.value == defaults["model"]["mode"]
    assert cm.ocr().model.default_spec.value == defaults["model"]["default_spec"]
    assert cm.ocr().device.gpu_enabled == defaults["device"]["gpu_enabled"]
    assert cm.ocr().thresholds.text_score == defaults["thresholds"]["text_score"]
    assert cm.ocr().language == defaults["language"]


# ---- ocr 命令 ----


def test_ocr_text_output(monkeypatch, config_manager, tmp_path):
    monkeypatch.setattr(
        "cli.commands.ocr.build_ocr_manager", lambda cfg: FakeOCRManager(cfg)
    )
    img = tmp_path / "test.png"
    img.write_bytes(b"fake-image-bytes")
    result = runner.invoke(
        app,
        ["ocr", str(img), "--config", str(config_manager.path)],
    )
    assert result.exit_code == 0
    assert "你好  (0.990)" in result.stdout
    assert "-- 规格=small" in result.stdout


def test_ocr_json_output(monkeypatch, config_manager, tmp_path):
    monkeypatch.setattr(
        "cli.commands.ocr.build_ocr_manager", lambda cfg: FakeOCRManager(cfg)
    )
    img = tmp_path / "test.png"
    img.write_bytes(b"fake-image-bytes")
    result = runner.invoke(
        app,
        [
            "ocr",
            str(img),
            "--spec",
            "tiny",
            "--json",
            "--config",
            str(config_manager.path),
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["spec"] == "tiny"
    assert payload["items"][0]["text"] == "你好"
    # CLI 不做清洗：text 为原始拼接（含空行产生的换行），清洗由未来消费方实现
    assert payload["text"] == "你好\n"


def test_ocr_missing_image(monkeypatch, config_manager, tmp_path):
    monkeypatch.setattr(
        "cli.commands.ocr.build_ocr_manager", lambda cfg: FakeOCRManager(cfg)
    )
    result = runner.invoke(
        app,
        [
            "ocr",
            str(tmp_path / "nonexistent.png"),
            "--config",
            str(config_manager.path),
        ],
    )
    assert result.exit_code != 0


def test_ocr_success_closes_manager(monkeypatch, config_manager, tmp_path):
    """M: CLI OCR 在 finally 中释放 manager（close 必被调用）。"""
    manager = FakeOCRManager(None)
    _patch_ocr_manager(monkeypatch, manager)
    img = tmp_path / "test.png"
    img.write_bytes(b"fake-image-bytes")
    result = runner.invoke(app, ["ocr", str(img), "--config", str(config_manager.path)])
    assert result.exit_code == 0
    assert manager.closed is True


def test_ocr_error_closes_manager_and_reports_friendly(
    monkeypatch, config_manager, tmp_path
):
    """H-2/M: 识别失败 → 友好错误 + 退出码 1，且仍 close。"""
    manager = FakeOCRManager(None)
    manager.fail_with = OcrError("boom")
    _patch_ocr_manager(monkeypatch, manager)
    img = tmp_path / "test.png"
    img.write_bytes(b"fake-image-bytes")
    result = runner.invoke(app, ["ocr", str(img), "--config", str(config_manager.path)])
    assert result.exit_code == 1
    assert "OCR 失败" in result.output
    assert manager.closed is True
