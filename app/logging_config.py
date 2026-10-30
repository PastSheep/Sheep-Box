"""全局日志配置（单一来源）。

main（GUI）与 CLI 入口都从这里初始化 root logger，避免各模块私自配置
handler / formatter，也保证 CLI 场景下 INFO 日志（如 OCR 引擎加载）可见。
"""

import copy
from logging.config import dictConfig
from typing import Any

__all__ = ["LOG_CONFIG", "configure_logging"]

LOG_CONFIG: dict[str, Any] = {
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


def configure_logging(level: str = "INFO") -> None:
    """应用全局日志配置（幂等，可重复调用）。

    深拷贝 :data:`LOG_CONFIG` 后再改 root 级别并 ``dictConfig``，避免修改
    模块级配置字典（重复调用与测试之间不串状态）。

    Args:
        level: root logger 级别，默认 ``INFO``。
    """
    config: dict[str, Any] = copy.deepcopy(LOG_CONFIG)
    root: dict[str, Any] = config["root"]
    root["level"] = level
    dictConfig(config)
