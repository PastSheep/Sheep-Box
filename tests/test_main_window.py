"""主窗口写盘失败后的回滚与提示（offscreen）。

覆盖审计复审指出的 #8：用户切主题/语言/刷新间隔时界面先变、``save_app``
失败只记日志，界面与磁盘不一致且没有任何反馈。修复后应回滚到磁盘旧值，
并在设置页显示提示。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from config.manager import ConfigManager
from gui.theme.appearance import apply_appearance
from gui.view.main_window import MainWindow

CONFIG_YAML = """\
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
def window(tmp_path):
    """构造一个指向临时配置的主窗口。"""
    app = QApplication.instance() or QApplication([])
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG_YAML, encoding="utf-8")
    manager = ConfigManager(cfg)
    win = MainWindow(config_manager=manager)
    try:
        yield win, manager
    finally:
        win.close()
        app.processEvents()


def _make_readonly(manager: ConfigManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """让写盘抛 PermissionError（模拟只读文件 / 被安全软件占用）。"""

    def _fail(_data: object) -> None:
        raise PermissionError("配置文件只读")

    monkeypatch.setattr(manager, "_atomic_write", _fail)


def test_theme_save_failure_rolls_back_and_shows_notice(window, monkeypatch) -> None:
    """主题写盘失败：外观回滚到磁盘值，下拉复位，并出现提示。"""
    win, manager = window
    assert win._settings._theme_combo.currentData() == "light"
    _make_readonly(manager, monkeypatch)

    win._on_theme_selected("dark")

    assert win._tokens == apply_appearance("light")
    assert win._settings._theme_combo.currentData() == "light"
    assert not win._settings._notice.isHidden()
    assert win._settings._notice.text()


def test_status_bar_save_failure_rolls_back_interval(window, monkeypatch) -> None:
    """状态栏间隔写盘失败：定时器回到磁盘上的旧周期并提示。"""
    win, manager = window
    previous = win._timer.interval()
    win._timer.setInterval(previous + 1000)
    _make_readonly(manager, monkeypatch)

    win._save_status_bar({"refresh_interval_ms": previous + 1000})

    assert win._timer.interval() == previous
    assert not win._settings._notice.isHidden()
