"""Sheep Box 项目启动入口。

日志全局配置统一收敛在 :mod:`app.logging_config`（main 与 CLI 共用），
各模块只通过 ``logging.getLogger(__name__)`` 获取 logger，不私自配置
handler / formatter。

启动方式：
- 默认：启动桌面设置界面（PySide6）；
- ``--no-gui``：无头模式，仅初始化日志后退出（不加载 PySide6）。

退出码：成功 ``0``。
"""

import argparse
import logging
import sys
from typing import TYPE_CHECKING

from app.logging_config import configure_logging

if TYPE_CHECKING:
    from config.manager import ConfigManager

logger = logging.getLogger(__name__)


def _build_config_manager() -> "ConfigManager | None":
    """构建通用配置中心；config 无效时返回 None（不阻塞 GUI 启动）。

    界面语言属程序偏好：config 无效时回退默认，GUI 仍可启动。
    """
    from app.bootstrap import build_config_manager
    from common.exceptions import ConfigError

    try:
        return build_config_manager()
    except ConfigError:
        logger.warning("配置读取失败，界面语言偏好不做持久化", exc_info=True)
        return None


def _read_ui_language(config_manager: "ConfigManager | None") -> str | None:
    """从配置读取界面语言；config 无效时返回 None（回退默认 zh_CN）。"""
    from common.exceptions import ConfigError

    if config_manager is None:
        return None
    try:
        return config_manager.app().ui_language
    except ConfigError:
        logger.warning("读取界面语言失败，回退默认 zh_CN", exc_info=True)
        return None


def main() -> int:
    """项目入口，负责全局日志配置并按参数启动。

    Returns:
        进程退出码。
    """
    configure_logging()
    parser = argparse.ArgumentParser(description="Sheep Box")
    parser.add_argument(
        "--no-gui", action="store_true", help="无头模式：不启动 GUI，仅初始化日志后退出"
    )
    args = parser.parse_args()

    if args.no_gui:
        logger.info("service started")
        return 0

    # GUI 分支延迟导入：无头模式与配置命令不加载 PySide6 / GUI 栈
    from gui.view.main_window import run_gui

    config_manager = _build_config_manager()
    return run_gui(_read_ui_language(config_manager), config_manager)


if __name__ == "__main__":
    sys.exit(main())
