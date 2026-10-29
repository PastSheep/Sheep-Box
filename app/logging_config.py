"""全局日志配置（单一来源）。

main（GUI）与 CLI 入口都从这里初始化 root logger，避免各模块私自配置
handler / formatter，也保证 CLI 场景下 INFO 日志（如 OCR 引擎加载）可见。
"""

from logging.config import dictConfig
from typing import Any

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


def setup_logging(level: str = "INFO") -> None:
    """应用全局日志配置（幂等，可重复调用）。

    Args:
        level: root logger 级别，默认 ``INFO``。
    """
    config: dict[str, Any] = dict(LOG_CONFIG)
    root: dict[str, Any] = dict(config["root"])
    root["level"] = level
    config["root"] = root
    dictConfig(config)
