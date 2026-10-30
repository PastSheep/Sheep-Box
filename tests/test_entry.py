"""入口、全局日志与延迟导入契约测试。

覆盖：
- ``main.py`` 返回码：``--no-gui`` 为 0，成功透传 ``run_gui``；
- 全局日志配置单一来源且不修改模块级 ``LOG_CONFIG``；
- ``import cli.app`` / ``import app.bootstrap`` 不加载重量依赖（无 GUI / OCR 栈）。
"""

import logging
import subprocess
import sys
from pathlib import Path

import main as main_module
from app.logging_config import LOG_CONFIG, configure_logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    """在项目根目录以子进程执行代码（隔离当前测试进程的模块缓存）。"""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_no_gui_returns_zero(monkeypatch):
    monkeypatch.setattr(main_module, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["main.py", "--no-gui"])
    assert main_module.main() == 0


def test_gui_success_returns_run_gui_code(monkeypatch):
    monkeypatch.setattr(main_module, "configure_logging", lambda: None)
    monkeypatch.setattr(main_module, "_read_ui_language", lambda: "zh_CN")
    monkeypatch.setattr(sys, "argv", ["main.py"])
    import gui.view.main_window as main_window_module

    monkeypatch.setattr(main_window_module, "run_gui", lambda language: 7)
    assert main_module.main() == 7


def test_configure_logging_does_not_mutate_log_config():
    """configure_logging 深拷贝配置，不修改模块级 LOG_CONFIG。"""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        original_level = LOG_CONFIG["root"]["level"]
        configure_logging("DEBUG")
        assert LOG_CONFIG["root"]["level"] == original_level
        assert root.level == logging.DEBUG
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_import_cli_app_does_not_load_heavy_dependencies():
    code = (
        "import sys, cli.app; "
        "heavy = [m for m in sys.modules "
        "if m.split('.')[0] in ('rapidocr', 'onnxruntime', 'PySide6')]; "
        "print(len(heavy))"
    )
    proc = _run_python(code)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "0"


def test_import_bootstrap_does_not_load_config_or_ocr_stack():
    code = (
        "import sys, app.bootstrap; "
        "print(int(any(m.split('.')[0] in ('rapidocr', 'onnxruntime', 'PySide6') "
        "or m == 'config.manager' for m in sys.modules)))"
    )
    proc = _run_python(code)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "0"
