"""设置界面控制器单元测试（无 Qt 依赖）。

验证：读取当前值、写回后重载、未提供字段保留、输入校验、恢复默认值、
round-trip 写回保留注释。
"""

import pytest

from gui.controller.settings_controller import SettingsController


def test_load_returns_current_values(config_manager):
    c = SettingsController(config_manager)
    v = c.load()
    assert v["mode"] == "small"
    assert v["default_spec"] == "small"
    assert v["gpu_enabled"] is True
    assert v["text_score"] == 0.5
    assert v["box_thresh"] == 0.5
    assert v["unclip_ratio"] == 1.6
    assert v["language"] == "zh"
    models = v["models"]
    assert isinstance(models, dict)
    assert set(models) == {"tiny", "small", "medium"}


def test_save_updates_yaml_and_reloads(config_manager):
    c = SettingsController(config_manager)
    c.save(
        {
            "mode": "tiny",
            "default_spec": "tiny",
            "gpu_enabled": False,
            "text_score": 0.4,
            "box_thresh": 0.6,
            "unclip_ratio": 2.0,
            "language": "en",
        }
    )
    v = c.load()
    assert v["mode"] == "tiny"
    assert v["default_spec"] == "tiny"
    assert v["gpu_enabled"] is False
    assert v["text_score"] == 0.4
    assert v["box_thresh"] == 0.6
    assert v["unclip_ratio"] == 2.0
    assert v["language"] == "en"


def test_save_keeps_untouched_fields(config_manager):
    c = SettingsController(config_manager)
    current = c.load()
    # 仅改 model 段（其余字段沿用当前值），device / thresholds / language 应保留
    c.save({**current, "mode": "medium", "default_spec": "medium"})
    v = c.load()
    assert v["mode"] == "medium"
    assert v["default_spec"] == "medium"
    assert v["gpu_enabled"] is True
    assert v["text_score"] == 0.5
    assert v["box_thresh"] == 0.5
    assert v["unclip_ratio"] == 1.6
    assert v["language"] == "zh"


def test_validate_values_rejects_invalid(config_manager):
    c = SettingsController(config_manager)
    errs = c.validate_values(
        {
            "mode": "huge",
            "default_spec": "x",
            "text_score": 1.5,
            "box_thresh": -0.1,
            "unclip_ratio": 0,
            "language": "",
        }
    )
    assert len(errs) >= 4


def test_validate_values_accepts_valid(config_manager):
    c = SettingsController(config_manager)
    errs = c.validate_values(
        {
            "mode": "all",
            "default_spec": "medium",
            "text_score": 0.5,
            "box_thresh": 0.5,
            "unclip_ratio": 1.6,
            "language": "zh",
        }
    )
    assert errs == []


def test_save_rejects_invalid_values(config_manager):
    c = SettingsController(config_manager)
    with pytest.raises(ValueError):
        c.save(
            {
                "mode": "huge",
                "default_spec": "small",
                "gpu_enabled": True,
                "text_score": 0.5,
                "box_thresh": 0.5,
                "unclip_ratio": 1.6,
                "language": "zh",
            }
        )


def test_restore_defaults(config_manager):
    c = SettingsController(config_manager)
    c.save(
        {
            "mode": "all",
            "default_spec": "tiny",
            "gpu_enabled": False,
            "text_score": 0.9,
            "box_thresh": 0.9,
            "unclip_ratio": 3.0,
            "language": "ja",
        }
    )
    c.restore_defaults()
    v = c.load()
    assert v["mode"] == "small"
    assert v["default_spec"] == "small"
    assert v["gpu_enabled"] is True
    assert v["text_score"] == 0.5
    assert v["box_thresh"] == 0.5
    assert v["unclip_ratio"] == 1.6
    assert v["language"] == "zh"


def test_save_roundtrip_keeps_comment(config_manager):
    from config.manager import ConfigManager

    cfg = config_manager.path
    # 在原 yaml 顶部加注释，重建 ConfigManager 后保存，验证注释被保留
    cfg.write_text(
        "# 顶部说明注释\n" + cfg.read_text(encoding="utf-8"), encoding="utf-8"
    )
    cm = ConfigManager(cfg)
    c = SettingsController(cm)
    current = c.load()
    c.save({**current, "mode": "tiny"})
    text = cfg.read_text(encoding="utf-8")
    assert "# 顶部说明注释" in text  # round-trip 保留注释
