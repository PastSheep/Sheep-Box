"""Sheep Box 项目启动入口。

日志全局配置统一收敛在本入口（dictConfig），各模块只通过
``logging.getLogger(__name__)`` 获取 logger，不私自配置 handler / formatter。
"""

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
    """项目入口，负责全局日志配置并启动服务。"""
    dictConfig(LOG_CONFIG)
    logger.info("service started")


if __name__ == "__main__":
    main()
