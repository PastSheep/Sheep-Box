"""Sheep Box 项目启动入口。

日志全局配置统一收敛在本入口（dictConfig），各模块只通过
``logging.getLogger(__name__)`` 获取 logger，不私自配置 handler / formatter。

启动方式：
- 默认（无参数或 ``--gui``）：启动桌面设置界面（PySide6，暂不接入 OCR 识别）；
- ``--no-gui``：无头模式，仅初始化日志后退出（不加载 PySide6）。
"""

import argparse
import logging
from logging.config import dictConfig

LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {"format": "%(asctime)s %(name)s %(levelname)s %(message)s"}
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "console",
            "stream": "ext://sys.stdout",
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["stdout"],
    },
}

logger = logging.getLogger(__name__)


def main() -> None:
    """项目入口，负责全局日志配置并按参数启动。"""
    dictConfig(LOG_CONFIG)
    parser = argparse.ArgumentParser(description="Sheep Box")
    parser.add_argument(
        "--no-gui", action="store_true", help="无头模式：不启动 GUI，仅初始化日志后退出"
    )
    args = parser.parse_args()

    if not args.no_gui:
        # 默认启动 GUI（普通用户入口）；组装收敛到 bootstrap，延迟导入避免无头加载
        from app.bootstrap import build_settings_controller
        from gui.view.main_window import run_gui

        run_gui(build_settings_controller())
        return

    logger.info("service started")


if __name__ == "__main__":
    main()
