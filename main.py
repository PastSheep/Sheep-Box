"""Sheep Box 项目启动入口。

日志全局配置统一收敛在本入口（dictConfig），各模块只通过
``logging.getLogger(__name__)`` 获取 logger，不私自配置 handler / formatter。

启动方式：
- 默认：无参数，仅初始化日志并退出；
- ``--gui``：启动桌面设置界面（PySide6，暂不接入 OCR 识别）。
"""

import argparse
import logging
from logging.config import dictConfig
from pathlib import Path

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
    parser.add_argument("--gui", action="store_true", help="启动图形界面（设置界面）")
    args = parser.parse_args()

    if args.gui:
        # 延迟导入，非 GUI 启动不加载 PySide6
        from gui.view.main_window import run_gui

        config_path = Path(__file__).resolve().parent / "config" / "config.yaml"
        run_gui(config_path)
        return

    logger.info("service started")


if __name__ == "__main__":
    main()
