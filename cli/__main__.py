"""``python -m cli`` 入口。"""

from app.logging_config import configure_logging
from cli.app import run


def main() -> None:
    """初始化全局日志后执行 CLI（import 本模块时不配置，避免污染宿主进程）。"""
    configure_logging()
    run()


if __name__ == "__main__":
    main()
