"""统一组装根：集中所有依赖的构建规则。

GUI 由 main.py 作为组装根调用本模块；CLI 各命令因入口独立且 ``--config``
动态传入，统一调用本模块的工厂函数。改依赖构造方式只改这里，不再散落在调用方。
"""

from pathlib import Path

from config.manager import ConfigManager
from gui.controller.settings_controller import SettingsController
from service.ocr.manager import OCRManager

__all__ = [
    "default_config_path",
    "build_config_manager",
    "build_ocr_manager",
    "build_settings_controller",
]


def default_config_path() -> Path:
    """返回默认配置文件路径（项目根 ``config/config.yaml``）。"""
    return Path(__file__).resolve().parent.parent / "config" / "config.yaml"


def build_config_manager(config_path: str | Path | None = None) -> ConfigManager:
    """构建通用配置中心（配置路径解析的单一来源）。

    Args:
        config_path: 配置文件路径；缺省使用 :func:`default_config_path`。
    """
    return ConfigManager(
        config_path if config_path is not None else default_config_path()
    )


def build_ocr_manager(config_path: str | Path | None = None) -> OCRManager:
    """构建 OCR 管理器（未来换引擎 / 多后端时，装配统一收敛于此）。"""
    return OCRManager(build_config_manager(config_path))


def build_settings_controller(
    config_path: str | Path | None = None,
) -> SettingsController:
    """构建设置界面控制器（复用配置中心，无 Qt 依赖）。"""
    return SettingsController(build_config_manager(config_path))
