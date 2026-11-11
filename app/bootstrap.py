"""统一组装根：集中所有依赖的构建规则。

GUI 由 main.py 作为组装根调用本模块。改依赖构造方式只改这里，不再散落在调用方。

注意：构建函数在函数体内延迟导入依赖，模块顶层只保留类型检查用途的导入，
避免 ``import app.bootstrap`` 即连带加载配置栈 / OCR 引擎 / PySide6 等重量依赖。
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型检查时导入，避免运行时加载重量依赖
    from config.manager import ConfigManager
    from service.ocr.manager import OCRManager

__all__ = [
    "build_config_manager",
    "build_ocr_manager",
    "default_config_path",
]


def default_config_path() -> Path:
    """返回默认配置文件路径（项目根 ``config/config.yaml``）。"""
    return Path(__file__).resolve().parent.parent / "config" / "config.yaml"


def build_config_manager(config_path: str | Path | None = None) -> "ConfigManager":
    """构建通用配置中心（配置路径解析的单一来源）。

    Args:
        config_path: 配置文件路径；缺省使用 :func:`default_config_path`。
    """
    from config.manager import ConfigManager

    return ConfigManager(
        config_path if config_path is not None else default_config_path()
    )


def build_ocr_manager(config_path: str | Path | None = None) -> "OCRManager":
    """构建 OCR 管理器（未来换引擎 / 多后端时，装配统一收敛于此）。

    延迟导入 OCR 栈：仅在实际构建时加载，避免无 OCR 场景（如 GUI 设置页）
    提前加载引擎依赖。
    """
    from service.ocr.manager import OCRManager

    return OCRManager(build_config_manager(config_path))
