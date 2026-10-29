"""CLI 命令单元测试。

config 命令通过 ``--config`` 注入临时配置，不触碰真实 config.yaml；
ocr 命令 mock ``OCRManager``，验证参数解析与文本/JSON 输出格式。
"""

import json

from typer.testing import CliRunner

from cli.app import app
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

    def set_model_spec(self, spec: ModelSpec) -> None:
        self.active_spec = ModelSpec(spec)

    def recognize(self, image_bytes: bytes) -> OCRResult:
        return _fake_ocr_result()


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
    assert payload["clean_text"] == "你好"  # 空行被清洗


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
