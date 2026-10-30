"""Sheep Box 项目启动入口。

日志全局配置统一收敛在 :mod:`app.logging_config`（main 与 CLI 共用），
各模块只通过 ``logging.getLogger(__name__)`` 获取 logger，不私自配置
handler / formatter。

启动方式：
- 默认：启动桌面设置界面（PySide6）；
- ``--no-gui``：无头模式，仅初始化日志后退出（不加载 PySide6）。

退出码：成功 ``0``；GUI 启动失败（配置无效）返回 ``2``。
"""

import argparse
import logging
import os
import sys

from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _show_startup_error(message: str) -> None:
    """尝试用消息框提示 GUI 启动失败（无显示环境时仅记日志，不二次崩溃）。

    无头 / offscreen 环境（如自动化测试）下不弹模态框，避免阻塞进程。

    Args:
        message: 展示给用户的错误信息。
    """
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        logger.error("GUI 启动失败提示（offscreen 环境不弹窗）: %s", message)
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "Sheep Box 启动失败", message)
        app.quit()
    except Exception:
        logger.exception("无法显示 GUI 启动错误提示框")


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
    from app.bootstrap import build_settings_controller
    from common.exceptions import ConfigError

    try:
        controller = build_settings_controller()
    except ConfigError:
        logger.critical("GUI 启动失败：配置无效", exc_info=True)
        _show_startup_error("配置无效，无法启动设置界面，请检查 config.yaml。")
        return 2

    from gui.view.main_window import run_gui

    return run_gui(controller)


if __name__ == "__main__":
    sys.exit(main())
