"""Sheep Box 项目启动入口。

日志全局配置统一收敛在 :mod:`app.logging_config`（main 与 CLI 共用），
各模块只通过 ``logging.getLogger(__name__)`` 获取 logger，不私自配置
handler / formatter。

启动方式：
- 默认（无参数或 ``--gui``）：启动桌面设置界面（PySide6）；
- ``--no-gui``：无头模式，仅初始化日志后退出（不加载 PySide6）。

退出码：成功 ``0``；GUI 启动失败（配置 / OCR 引擎加载异常）返回 ``1``。
"""

import argparse
import logging

from app.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    """项目入口，负责全局日志配置并按参数启动。

    Returns:
        进程退出码。
    """
    setup_logging()
    parser = argparse.ArgumentParser(description="Sheep Box")
    parser.add_argument(
        "--no-gui", action="store_true", help="无头模式：不启动 GUI，仅初始化日志后退出"
    )
    args = parser.parse_args()

    if not args.no_gui:
        # 默认启动 GUI（普通用户入口）；组装收敛到 bootstrap，延迟导入避免无头加载
        from app.bootstrap import build_settings_controller
        from common.exceptions import ConfigError, OcrEngineError
        from gui.view.main_window import run_gui

        try:
            return run_gui(build_settings_controller())
        except (ConfigError, OcrEngineError) as exc:
            logger.critical("GUI 启动失败: %s", exc, exc_info=True)
            return 1

    logger.info("service started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
