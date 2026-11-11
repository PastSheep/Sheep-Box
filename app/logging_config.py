"""全局日志配置（单一来源）。

项目启动入口（main.py）从这里初始化 root logger，避免各模块私自配置
handler / formatter；日志走 stderr，stdout 保持干净留给业务输出。
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
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
            # 日志一律走 stderr：stdout 留给业务输出，未来接管道或打包成
            # 无控制台程序时都不会被日志混入。
            "stream": "ext://sys.stderr",
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
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
