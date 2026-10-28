"""CLI 命令入口模块（typer）。

提供 ``ocr`` 与 ``config`` 子命令，作为可脚本化的无头操作入口，与 GUI 互补
（GUI 暂不接入 OCR，CLI 即时接入，便于实机验证与自动化回归）。
"""

from pathlib import Path


def config_path() -> Path:
    """返回默认配置文件路径（项目根 ``config/config.yaml``）。"""
    return Path(__file__).resolve().parent.parent / "config" / "config.yaml"
