"""CLI 主应用：聚合各功能命令与子应用。

扩容：新增功能时在 :mod:`cli.commands` 导出其命令函数或 ``Typer`` 子应用，
在此以 ``app.command(...)`` 或 ``app.add_typer(...)`` 一行挂载即可。

日志：全局日志仅在主执行路径（``python -m cli`` / ``python cli/app.py``）
调用 :func:`app.logging_config.configure_logging`，模块 import 时不配置，
避免污染 pytest 等宿主进程。
"""

import typer

from app.logging_config import configure_logging
from cli.commands import config_app, ocr_cmd
from common.exceptions import SheepBoxError

app = typer.Typer(
    help="Sheep Box CLI",
    no_args_is_help=True,
    add_completion=False,
)

# ocr 为顶层命令：python -m cli ocr <image>
app.command("ocr")(ocr_cmd)
# config 为子应用：python -m cli config get/set/list/reset
app.add_typer(config_app, name="config")


def run() -> None:
    """执行 CLI：业务异常以错误信息 + 非零退出码结束。"""
    try:
        app()
    except typer.Exit:
        raise
    except SheepBoxError as exc:
        typer.echo(f"错误: {exc}", err=True)
        raise SystemExit(1) from exc
    except Exception as exc:
        typer.echo(f"未预期错误: {exc}", err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    configure_logging()
    run()
