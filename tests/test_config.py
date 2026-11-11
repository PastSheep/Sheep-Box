"""通用配置中心单元测试。

覆盖：YAML 加载、必填严格校验、可选回退、非法枚举、文件缺失、运行时热更新。
"""

import threading
import time

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


def test_app_theme_default(tmp_path):
    """app.theme 缺省回退浅色（light）。"""
    path = _write(tmp_path, VALID_YAML)
    cfg = load_config(path)
    assert cfg.app.theme.value == "light"


def test_app_theme_override(tmp_path):
    """提供 app.theme: dark 时生效（黑白主题可配置）。"""
    content = VALID_YAML + "\napp:\n  theme: dark\n"
    path = _write(tmp_path, content)
    cfg = load_config(path)
    assert cfg.app.theme.value == "dark"


def test_app_unknown_key_rejected(tmp_path):
    """app 段未知键（extra=forbid）直接拒绝。"""
    content = VALID_YAML + "\napp:\n  unknown_key: 1\n"
    path = _write(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_save_app_writes_ui_language(tmp_path):
    """save_app 写回 app.ui_language 并生效（round-trip）。"""
    path = _write(tmp_path, VALID_YAML)
    cm = ConfigManager(path)
    cm.save_app({"ui_language": "en_US"})
    assert cm.app().ui_language == "en_US"


def test_save_app_writes_theme(tmp_path):
    """save_app 写回 app.theme 并生效（round-trip）。"""
    path = _write(tmp_path, VALID_YAML)
    cm = ConfigManager(path)
    cm.save_app({"theme": "dark"})
    assert cm.app().theme.value == "dark"


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


def test_save_app_wraps_oserror_as_config_error(tmp_path, monkeypatch):
    """写盘侧的 OSError（只读目录、文件被占用）统一归一为 ConfigError。

    修复前 ``save_app`` 只承诺 ConfigError、实现却会漏出裸 OSError，
    GUI/CLI 的 ``except ConfigError`` 接不住，用户看到 Traceback。
    """
    path = _write(tmp_path, VALID_YAML)
    cm = ConfigManager(path)

    def _fail(_data):
        raise PermissionError("配置文件只读")

    monkeypatch.setattr(cm, "_atomic_write", _fail)
    with pytest.raises(ConfigError):
        cm.save_app({"theme": "dark"})


def test_config_file_lock_serializes_writers(tmp_path):
    """跨进程锁必须让两个写者的临界区严格不重叠。"""
    from config.manager import _config_file_lock

    path = _write(tmp_path, VALID_YAML)
    barrier = threading.Barrier(2)
    spans: list[tuple[float, float]] = []

    def _hold(name: str) -> None:
        del name
        barrier.wait()
        with _config_file_lock(path):
            start = time.monotonic()
            time.sleep(0.05)
            spans.append((start, time.monotonic()))

    threads = [threading.Thread(target=_hold, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(spans) == 2
    spans.sort()
    assert spans[1][0] >= spans[0][1], "两个写者的临界区发生了重叠"


def test_config_file_lock_lives_beside_config(tmp_path):
    """锁文件与配置同目录：不同 %TEMP% 的进程之间也能互斥。"""
    from config.manager import _config_file_lock

    path = _write(tmp_path, VALID_YAML)
    lock = tmp_path / f".{path.name}.lock"
    assert not lock.exists()
    with _config_file_lock(path):
        assert lock.exists()


def test_concurrent_saves_keep_both_sections(tmp_path, monkeypatch):
    """GUI 与 CLI 同时写不同段时，两边的键都要留在文件里。

    用「进入 ``_atomic_write`` 后先睡一会儿」放大 read-modify-replace 窗口：
    没有任何跨进程互斥时，两个写者都基于同一份旧快照写回，后写者会覆盖前者。
    """
    path = _write(tmp_path, VALID_YAML)
    left = ConfigManager(path)
    right = ConfigManager(path)
    for manager in (left, right):
        original = manager._atomic_write

        def _slow(data, _original=original):
            time.sleep(0.02)
            _original(data)

        monkeypatch.setattr(manager, "_atomic_write", _slow)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _save(manager: ConfigManager, update: dict[str, object]) -> None:
        try:
            barrier.wait()
            manager.save_app(update)
        except BaseException as exc:  # noqa: BLE001 - 线程内异常需带回主线程
            errors.append(exc)

    threads = [
        threading.Thread(target=_save, args=(left, {"theme": "dark"})),
        threading.Thread(target=_save, args=(right, {"ui_language": "en_US"})),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    cfg = load_config(path)
    assert cfg.app.theme.value == "dark"
    assert cfg.app.ui_language == "en_US"
